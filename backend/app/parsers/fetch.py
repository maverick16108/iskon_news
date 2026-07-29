"""Загрузка страниц.

iskconnews.org закрыт Cloudflare: обычный requests/httpx получает 403
«Just a moment...». Помогает curl_cffi — он воспроизводит TLS-отпечаток
настоящего Chrome. Проверено: статья отдаётся 200, текст извлекается.
"""

from __future__ import annotations

import asyncio
import logging

import trafilatura
from curl_cffi import requests as curl_requests

log = logging.getLogger(__name__)

IMPERSONATE = "chrome124"
TIMEOUT = 40

# dandavats.com отдаёт 429 при частых запросах подряд, поэтому ходим
# по статьям с паузой и повторяем попытку с нарастающей задержкой.
RETRY_STATUSES = {429, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (3, 8)


class FetchError(RuntimeError):
    pass


def _fetch_sync(url: str) -> tuple[int, str]:
    try:
        response = curl_requests.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT)
    except Exception as exc:  # curl_cffi поднимает свои типы ошибок
        raise FetchError(f"Не удалось загрузить {url}: {exc}") from exc
    return response.status_code, response.text


async def fetch_html(url: str) -> str:
    """Скачивает страницу, не блокируя event loop. При 429 повторяет попытку."""
    last_status = 0

    for attempt in range(MAX_ATTEMPTS):
        status, text = await asyncio.to_thread(_fetch_sync, url)

        if status == 200:
            return text

        last_status = status
        if status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            break

        delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        log.info("%s вернул HTTP %d, повтор через %d с", url, status, delay)
        await asyncio.sleep(delay)

    raise FetchError(f"{url} вернул HTTP {last_status}")


def _fetch_bytes_sync(url: str) -> tuple[int, bytes, str]:
    try:
        response = curl_requests.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT)
    except Exception as exc:
        raise FetchError(f"Не удалось загрузить {url}: {exc}") from exc
    return response.status_code, response.content, response.headers.get("content-type", "")


async def fetch_bytes(url: str) -> tuple[bytes, str]:
    """Скачивает двоичный файл (картинку). Возвращает содержимое и тип."""
    last_status = 0

    for attempt in range(MAX_ATTEMPTS):
        status, content, content_type = await asyncio.to_thread(_fetch_bytes_sync, url)

        if status == 200:
            return content, content_type

        last_status = status
        if status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            break

        await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

    raise FetchError(f"{url} вернул HTTP {last_status}")


def extract_text(html: str) -> str | None:
    """Достаёт из HTML основной текст статьи без меню, футеров и комментариев."""
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        include_images=False,
        favor_precision=True,
    )


async def fetch_article_text(url: str) -> str | None:
    """Полный текст статьи по её адресу. None, если извлечь не удалось."""
    html = await fetch_html(url)
    return extract_text(html)
