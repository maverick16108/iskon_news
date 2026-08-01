"""Разговор с людьми в боте: подписка на оповещения и сводки.

Работаем длинным опросом (getUpdates), а не вебхуком: вебхук потребовал бы
отдельного публичного маршрута и настройки в Telegram, а опрос запускается
вместе с приложением и ничего снаружи не открывает.

Telegram не даёт списка тех, кто написал боту, — узнать о человеке можно
только из его же сообщения. Поэтому подписчик заводится в тот момент, когда
он сам пишет боту, а до этого мы о нём не знаем.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Article,
    ArticleView,
    BotState,
    BotSubscriber,
    Post,
    PostStatus,
    Source,
)
from app.telegram.client import TelegramError, _request

log = logging.getLogger(__name__)

# Сколько секунд держим соединение getUpdates открытым
POLL_TIMEOUT_SECONDS = 25

MENU = {
    "keyboard": [
        [{"text": "🔔 Оповещать о новостях"}, {"text": "🔕 Не оповещать"}],
        [{"text": "📊 Сводка сейчас"}],
    ],
    "resize_keyboard": True,
}

GREETING = (
    "Это бот редакции «Новости ИСККОН».\n\n"
    "Он сообщает, когда с сайтов-источников приходят свежие новости, "
    "чтобы их можно было переработать и опубликовать в канале.\n\n"
    "Кнопками ниже включите или выключите оповещения."
)


@dataclass
class FetchSummary:
    """Что принёс обход источников."""

    by_source: dict[str, int]
    ready_to_publish: int
    unviewed: int

    @property
    def added(self) -> int:
        return sum(self.by_source.values())


async def bot_state(db: AsyncSession) -> BotState:
    row = await db.scalar(select(BotState).limit(1))
    if row is None:
        row = BotState(update_offset=0)
        db.add(row)
        await db.flush()
    return row


async def _send(token: str, chat_id: str, text: str, *, with_menu: bool = True) -> None:
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if with_menu:
        payload["reply_markup"] = MENU
    await _request(token, "sendMessage", json=payload)


async def collect_summary(db: AsyncSession, by_source: dict[str, int] | None = None) -> FetchSummary:
    """Считает то, что интересно редактору: что готово и что не смотрели."""
    ready = await db.scalar(
        select(func.count(Post.id)).where(
            Post.status.in_([PostStatus.generated, PostStatus.edited])
        )
    )

    # Непросмотренная — та, которую не открывал вообще никто
    unviewed = await db.scalar(
        select(func.count(Article.id)).where(~Article.id.in_(select(ArticleView.article_id)))
    )

    return FetchSummary(
        by_source=by_source or {},
        ready_to_publish=ready or 0,
        unviewed=unviewed or 0,
    )


def render_summary(summary: FetchSummary, *, after_fetch: bool) -> str:
    portal = settings.portal_url.rstrip("/")
    lines: list[str] = []

    if after_fetch:
        if not summary.added:
            return ""  # писать «ничего не пришло» на каждый обход незачем
        lines.append(f"<b>Пришли новости: {summary.added}</b>")
        for name, count in sorted(summary.by_source.items(), key=lambda i: -i[1]):
            lines.append(f"• {html.escape(name)} — {count}")
        lines.append("")
    else:
        lines.append("<b>Сейчас в ленте</b>")

    lines.append(f"Готовы к публикации: {summary.ready_to_publish}")
    lines.append(f"Не просмотрено: {summary.unviewed}")
    lines.append("")
    # Ссылка ведёт в ленту, отсортированную по добавлению: у свежесобранных
    # новостей дата публикации бывает старой, и при сортировке по ней они
    # оказываются в конце списка — «12 новых» найти было негде.
    target = f"{portal}/?sort=fetched&order=desc" if after_fetch else portal
    lines.append(f'<a href="{html.escape(target)}">Открыть портал и опубликовать</a>')

    return "\n".join(lines)


async def notify_subscribers(db: AsyncSession, token: str, summary: FetchSummary) -> int:
    """Рассылает сводку подписчикам. Возвращает число доставленных."""
    text = render_summary(summary, after_fetch=True)
    if not text:
        return 0

    people = list(
        await db.scalars(
            select(BotSubscriber).where(
                BotSubscriber.notify.is_(True), BotSubscriber.is_blocked.is_(False)
            )
        )
    )

    delivered = 0
    for person in people:
        try:
            await _send(token, person.chat_id, text)
        except TelegramError as exc:
            # Человек мог заблокировать бота — отмечаем и больше не пишем,
            # иначе каждый обход будет упираться в одну и ту же ошибку
            message = str(exc).lower()
            if "blocked" in message or "chat not found" in message or "deactivated" in message:
                person.is_blocked = True
                log.info("Подписчик %s заблокировал бота", person.chat_id)
            else:
                log.warning("Не удалось написать %s: %s", person.chat_id, exc)
            continue

        person.last_notified_at = datetime.now(timezone.utc)
        delivered += 1

    await db.commit()
    return delivered


async def _handle_message(db: AsyncSession, token: str, message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return

    text = (message.get("text") or "").strip()
    sender = message.get("from") or {}

    person = await db.scalar(select(BotSubscriber).where(BotSubscriber.chat_id == chat_id))
    if person is None:
        person = BotSubscriber(
            chat_id=chat_id,
            username=sender.get("username"),
            full_name=" ".join(
                part for part in (sender.get("first_name"), sender.get("last_name")) if part
            )
            or None,
            notify=True,
        )
        db.add(person)
        await db.flush()

    # Написал — значит бот у него не заблокирован
    person.is_blocked = False

    if text.startswith("/start"):
        await _send(token, chat_id, GREETING)
        return

    if "Оповещать" in text and "Не" not in text:
        person.notify = True
        await _send(token, chat_id, "Оповещения включены. Напишу, когда придут новости.")
        return

    if "Не оповещать" in text:
        person.notify = False
        await _send(token, chat_id, "Оповещения выключены. Включить можно кнопкой ниже.")
        return

    if "Сводка" in text:
        summary = await collect_summary(db)
        await _send(token, chat_id, render_summary(summary, after_fetch=False))
        return

    await _send(token, chat_id, "Выберите действие кнопками ниже.")


async def poll_once(db: AsyncSession, token: str) -> int:
    """Забирает и обрабатывает накопившиеся сообщения.

    Ошибку не глотаем, а пробрасываем: вызывающий цикл должен на ней
    притормозить. Молча вернув ноль, мы бы крутились без пауз и слали
    в Telegram по три запроса в секунду.
    """
    state = await bot_state(db)

    updates = await _request(
        token,
        "getUpdates",
        json={
            "offset": state.update_offset,
            "timeout": POLL_TIMEOUT_SECONDS,
            "allowed_updates": ["message"],
        },
    )

    handled = 0
    for update in updates:
        state.update_offset = max(state.update_offset, int(update["update_id"]) + 1)
        message = update.get("message")
        if not message:
            continue
        try:
            await _handle_message(db, token, message)
            handled += 1
        except TelegramError as exc:
            log.warning("Не смогли ответить на сообщение: %s", exc)

    await db.commit()
    return handled
