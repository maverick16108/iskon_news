"""Фоновые задачи: обход источников по расписанию и разговор бота.

Обе задачи живут в том же процессе, что и приложение, — отдельной службы
для них не нужно. Обе берут в PostgreSQL советующую блокировку: если
приложение когда-нибудь запустят в несколько процессов, обходить источники
и вычитывать сообщения бота всё равно будет ровно один.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.config import settings
from app.db import SessionFactory
from app.models import FetchSettings, Source
from app.parsers.rss import fetch_feed
from app.telegram.bot import collect_summary, notify_subscribers, poll_once
from app.telegram.client import TelegramError
from app.telegram.config import current as telegram_config

log = logging.getLogger(__name__)

# Ключи советующих блокировок: произвольные, лишь бы не совпадали с чужими.
# Их две и они про разное. LOCK_SCHEDULER держится всё время жизни процесса
# и отвечает на вопрос «кто здесь планировщик». LOCK_FETCH берётся только на
# время самого обхода и отпускается сразу после — иначе ручная догрузка
# архива никогда не смогла бы начаться.
LOCK_SCHEDULER = 795_101
LOCK_FETCH = 795_103
LOCK_BOT = 795_102

# Как часто просыпаемся, чтобы проверить, не пора ли обходить источники
TICK_SECONDS = 60

# Пауза после ошибки опроса бота, чтобы не молотить впустую
BOT_ERROR_PAUSE_SECONDS = 30


async def _try_lock(db, key: int) -> bool:
    """Советующая блокировка на всё время жизни соединения."""
    return bool(await db.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))


async def _unlock(db, key: int) -> None:
    await db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


async def get_fetch_settings(db) -> FetchSettings:
    row = await db.scalar(select(FetchSettings).limit(1))
    if row is None:
        row = FetchSettings(is_enabled=False, interval_minutes=60)
        db.add(row)
        await db.flush()
    return row


def _due_values(
    enabled: bool, interval_minutes: int, last_run: datetime | None, now: datetime
) -> bool:
    """Пора ли обходить источники."""
    if not enabled:
        return False
    if last_run is None:
        return True
    return now - last_run >= timedelta(minutes=interval_minutes)


async def run_fetch_round() -> dict[str, int]:
    """Обходит активные источники. Возвращает, сколько добавлено по каждому."""
    added: dict[str, int] = {}

    async with SessionFactory() as db:
        # Обход всегда один: рядом может идти ручная догрузка архива
        if not await _try_lock(db, LOCK_FETCH):
            log.info("Обход уже идёт в другом месте — пропускаем этот тик")
            return added

        sources = list(await db.scalars(select(Source).where(Source.is_active.is_(True))))

        for source in sources:
            try:
                result = await fetch_feed(source, db)
            except Exception as exc:  # noqa: BLE001 — один источник не должен ронять обход
                log.warning("Источник %s: %s", source.name, exc)
                source.last_error = str(exc)
                await db.commit()
                continue

            if result["added"]:
                added[source.name] = result["added"]

        row = await get_fetch_settings(db)
        row.last_run_at = datetime.now(timezone.utc)
        row.last_result = (
            ", ".join(f"{name} — {count}" for name, count in added.items())
            if added
            else "новых публикаций нет"
        )
        await db.commit()
        await _unlock(db, LOCK_FETCH)

    return added


async def fetch_loop() -> None:
    """Просыпается раз в минуту и обходит источники, когда подошёл срок.

    Сессия здесь нужна только чтобы держать советующую блокировку: она живёт,
    пока живёт соединение. Данные читаем короткими сессиями.
    """
    async with SessionFactory() as db:
        if not await _try_lock(db, LOCK_SCHEDULER):
            log.info("Обход источников уже ведёт другой процесс — эта задача не нужна")
            return

        log.info("Планировщик обхода источников запущен")

        while True:
            try:
                # Настройки перечитываем отдельной сессией. В долгоживущей
                # объект остаётся в карте идентичности, а expire_on_commit
                # у нас выключен — и цикл не увидел бы ни включения из
                # интерфейса, ни смены интервала до перезапуска службы.
                async with SessionFactory() as settings_db:
                    row = await get_fetch_settings(settings_db)
                    await settings_db.commit()
                    enabled = row.is_enabled
                    interval = row.interval_minutes
                    last_run = row.last_run_at

                if _due_values(enabled, interval, last_run, datetime.now(timezone.utc)):
                    log.info("Пора обходить источники")
                    added = await run_fetch_round()
                    await _report(added)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — планировщик не должен умирать
                log.exception("Сбой в планировщике обхода")

            await asyncio.sleep(TICK_SECONDS)


async def _report(added: dict[str, int]) -> None:
    """Шлёт подписчикам сводку о том, что принёс обход."""
    if not added:
        return

    config = await telegram_config()
    if not config.token:
        return

    async with SessionFactory() as db:
        summary = await collect_summary(db, added)
        delivered = await notify_subscribers(db, config.token, summary)

    log.info("Сводка отправлена подписчикам: %d", delivered)


async def bot_loop() -> None:
    """Длинный опрос Telegram: отвечает людям, которые пишут боту."""
    if not settings.bot_polling:
        log.info("Опрос бота выключен в настройках (BOT_POLLING=false)")
        return

    async with SessionFactory() as db:
        if not await _try_lock(db, LOCK_BOT):
            log.info("Бота уже опрашивает другой процесс")
            return

        log.info("Опрос бота запущен")

        while True:
            try:
                config = await telegram_config()
                if not config.token:
                    await asyncio.sleep(TICK_SECONDS)
                    continue

                await poll_once(db, config.token)
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                # Самая частая причина — у бота включён вебхук, и тогда
                # Telegram отказывает в getUpdates. Ошибка постоянная,
                # поэтому ждём подольше и не пишем в лог одно и то же чаще
                log.warning("Опрос бота не удался: %s", exc)
                await asyncio.sleep(BOT_ERROR_PAUSE_SECONDS)
            except Exception:  # noqa: BLE001 — опрос не должен умирать
                log.exception("Сбой в опросе бота")
                await asyncio.sleep(BOT_ERROR_PAUSE_SECONDS)
