"""Публикация в мессенджер MAX.

Bot API у MAX похож на телеграмный, но отличается в трёх местах, и все три
важны для нас: токен идёт заголовком Authorization, а не в адресе; текст и
вложения уходят одним POST /messages; картинку можно передать прямой ссылкой,
не загружая файл.

Разметку MAX принимает свою — здесь используем HTML-подобную, ту же, что и
в Telegram: у нас в посте только жирный заголовок, ссылка в подписи
и переносы строк.

Проверить вживую пока не на чем: бот в MAX заводится только из кабинета
организации и после модерации. Поэтому здесь всё построено строго по
документации, а ошибки отправки не глотаются, а показываются редактору.
"""

from __future__ import annotations

import html
import logging

import httpx

from app.models import CHANNEL_TITLE, CHANNEL_URL

log = logging.getLogger(__name__)

API = "https://platform-api2.max.ru"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Столько картинок отправляем одним сообщением
MAX_ATTACHMENTS = 10


class MaxError(RuntimeError):
    """Ошибка обращения к MAX."""


async def _request(token: str, method: str, path: str, **kwargs) -> dict:
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
        try:
            response = await client.request(method, f"{API}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise MaxError(f"MAX недоступен: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise MaxError(f"MAX вернул не JSON (HTTP {response.status_code})") from exc

    if response.status_code >= 400:
        message = payload.get("message") or payload.get("code") or f"HTTP {response.status_code}"
        raise MaxError(str(message))

    return payload


async def check_bot(token: str) -> dict:
    """Кто подключён. Ничего не публикует."""
    return await _request(token, "GET", "/me")


async def check_channel(token: str, chat: str) -> dict:
    """Что известно о канале. Ничего не публикует."""
    try:
        info = await _request(token, "GET", f"/chats/{chat}")
    except MaxError as exc:
        return {"can_post": False, "member_error": str(exc)}

    # У MAX право писать отражается в статусе бота в чате
    status = (info.get("status") or "").lower()
    return {
        "title": info.get("title"),
        "status": status,
        "can_post": status in ("active", "admin", "owner"),
    }


def render_text(hashtags: str, title: str, body: str, signature: str) -> str:
    """Тот же формат, что и в Telegram: экранируем всё, потом выделяем заголовок."""
    esc = html.escape
    head = f"{esc(hashtags.strip())} <b>{esc(title.strip())}</b>".strip()
    channel = f'<b><a href="{CHANNEL_URL}">{esc(CHANNEL_TITLE)}</a></b>'
    tail = f"{esc(signature.strip())}\n{channel}".strip()
    return f"{head}\n\n{esc(body.strip())}\n\n{tail}"


async def send_post(token: str, chat: str, text: str, image_urls: list[str]) -> str | None:
    """Отправляет пост в канал. Возвращает идентификатор сообщения."""
    attachments = [
        {"type": "image", "payload": {"url": url}} for url in image_urls[:MAX_ATTACHMENTS]
    ]

    payload: dict = {"text": text, "format": "html"}
    if attachments:
        payload["attachments"] = attachments

    result = await _request(
        token, "POST", "/messages", params={"chat_id": chat}, json=payload
    )

    message = result.get("message") or {}
    body = message.get("body") or {}
    return str(body.get("mid") or message.get("mid") or "") or None
