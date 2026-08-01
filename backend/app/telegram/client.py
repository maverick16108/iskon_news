"""Отправка постов в канал через Telegram Bot API."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

API = "https://api.telegram.org"

# Подпись к медиагруппе у Telegram ограничена 1024 символами.
# Наш лимит поста — 1000, так что вписываемся, но проверяем.
MAX_CAPTION = 1024
MAX_PHOTOS = 10
TIMEOUT = 60


class TelegramError(RuntimeError):
    pass


@dataclass
class SentPost:
    message_id: int
    url: str


def render_html(hashtags: str, title: str, body: str, signature: str, channel_line: str) -> str:
    """Собирает пост в разметке Telegram.

    Экранируем всё как обычный текст и лишь потом оборачиваем заголовок
    в <b>: иначе амперсанд или угловая скобка из статьи сломали бы разбор
    на стороне Telegram, и сообщение не ушло бы.
    """
    esc = html.escape

    head = f"{esc(hashtags.strip())} <b>{esc(title.strip())}</b>".strip()
    tail = f"{esc(signature.strip())}\n{esc(channel_line.strip())}".strip()
    return f"{head}\n\n{esc(body.strip())}\n\n{tail}"


def _channel_url(channel: str, message_id: int) -> str:
    name = channel.lstrip("@")
    return f"https://t.me/{name}/{message_id}"


async def _request(token: str, method: str, **kwargs) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(f"{API}/bot{token}/{method}", **kwargs)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram недоступен: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramError(f"Telegram вернул не JSON (HTTP {response.status_code})") from exc

    if not payload.get("ok"):
        raise TelegramError(payload.get("description") or f"HTTP {response.status_code}")

    return payload["result"]


async def check_bot(token: str) -> dict:
    """Кто подключён. Ничего не публикует."""
    return await _request(token, "getMe", data={})


async def webhook_url(token: str) -> str | None:
    """Адрес вебхука, если он у бота стоит.

    Важно знать: пока вебхук включён, Telegram не отдаёт getUpdates, и бот
    не может принимать команды от людей. Отправке сообщений это не мешает.
    """
    info = await _request(token, "getWebhookInfo", data={})
    return info.get("url") or None


async def check_channel(token: str, channel: str) -> dict:
    """Виден ли канал и может ли бот в нём публиковать. Ничего не публикует."""
    me = await _request(token, "getMe", data={})
    chat = await _request(token, "getChat", data={"chat_id": channel})

    result = {"title": chat.get("title"), "type": chat.get("type")}

    # Право публиковать проверяем отдельно: без прав администратора
    # Telegram не отдаёт состав участников, и это само по себе ответ.
    try:
        member = await _request(
            token, "getChatMember", data={"chat_id": channel, "user_id": me["id"]}
        )
        result["status"] = member.get("status")
        result["can_post"] = bool(member.get("can_post_messages"))
    except TelegramError as exc:
        result["member_error"] = str(exc)
        result["can_post"] = False

    return result


async def send_post(
    *,
    token: str,
    channel: str,
    text: str,
    photos: list[Path],
) -> SentPost:
    """Публикует пост: с фотографиями — медиагруппой, иначе текстом.

    Файлы отправляем сами, а не ссылками: источники закрыты Cloudflare,
    и Telegram, скачивая по ссылке, получил бы 403.
    """
    if len(text) > MAX_CAPTION:
        raise TelegramError(
            f"В посте {len(text)} символов, Telegram принимает не больше {MAX_CAPTION}"
        )

    photos = [p for p in photos if p.exists()][:MAX_PHOTOS]

    if not photos:
        result = await _request(
            token,
            "sendMessage",
            data={
                "chat_id": channel,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
        )
        return SentPost(result["message_id"], _channel_url(channel, result["message_id"]))

    # Медиагруппа: подпись ставится только у первой фотографии
    media = []
    files = {}
    for index, path in enumerate(photos):
        key = f"photo{index}"
        item = {"type": "photo", "media": f"attach://{key}"}
        if index == 0:
            item["caption"] = text
            item["parse_mode"] = "HTML"
        media.append(item)
        files[key] = (path.name, path.read_bytes())

    import json as _json

    result = await _request(
        token,
        "sendMediaGroup",
        data={"chat_id": channel, "media": _json.dumps(media)},
        files=files,
    )

    first = result[0] if isinstance(result, list) else result
    message_id = first["message_id"]
    return SentPost(message_id, _channel_url(channel, message_id))
