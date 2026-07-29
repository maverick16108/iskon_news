"""Локальный кэш картинок.

iskconnews.org закрыт Cloudflare и отдаёт 403 не только на страницы, но и на
сами файлы изображений — по прямой ссылке браузер их не получит. Поэтому
картинки забирает бэкенд (он умеет ходить с TLS-отпечатком Chrome) и кладёт
рядом с собой, а фронтенд запрашивает их уже у нас.

Побочная польза: если источник удалит фотографию, у нас она останется.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

from app.parsers.fetch import FetchError, fetch_bytes

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "images"

# Больше этого не храним: в новостях таких картинок не бывает,
# а место на сервере не резиновое.
MAX_BYTES = 12 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def _path_for(url: str, extension: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{digest}{extension}"


def cached_path(url: str) -> Path | None:
    """Путь к уже скачанному файлу, если он есть."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    for extension in ALLOWED_TYPES.values():
        candidate = CACHE_DIR / f"{digest}{extension}"
        if candidate.exists():
            return candidate
    return None


async def ensure_cached(url: str) -> tuple[Path, str]:
    """Возвращает путь к файлу и его тип, при необходимости скачивая."""
    existing = cached_path(url)
    if existing:
        media_type = next(
            (t for t, ext in ALLOWED_TYPES.items() if ext == existing.suffix), "image/jpeg"
        )
        return existing, media_type

    content, content_type = await fetch_bytes(url)

    if len(content) > MAX_BYTES:
        raise FetchError(f"Картинка больше {MAX_BYTES // 1024 // 1024} МБ — не сохраняем")

    media_type = content_type.split(";")[0].strip().lower()
    extension = ALLOWED_TYPES.get(media_type)

    if extension is None:
        # Тип не сказали или сказали неправду — доверимся расширению в адресе
        suffix = Path(urlparse(url).path).suffix.lower()
        extension = suffix if suffix in ALLOWED_TYPES.values() else ".jpg"
        media_type = next(t for t, ext in ALLOWED_TYPES.items() if ext == extension)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(url, extension)
    path.write_bytes(content)

    log.info("Картинка сохранена: %s (%d КБ)", path.name, len(content) // 1024)
    return path, media_type
