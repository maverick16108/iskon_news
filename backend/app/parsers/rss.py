"""Разбор RSS/Atom-фидов и наполнение базы статьями."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from html import unescape

import feedparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, ContentQuality, Source
from app.parsers.fetch import FetchError, fetch_article_text

log = logging.getLogger(__name__)

# Хвост, который WordPress дописывает к анонсу в фиде
WP_TAIL = re.compile(r"The post .*? appeared first on .*?\.\s*$", re.S)

# Пауза между запросами к статьям одного источника
POLITE_DELAY_SECONDS = 1.5


def _strip_html(value: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", value, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = WP_TAIL.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _parsed_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def _first_image(entry) -> str | None:
    for media in entry.get("media_content", []) or []:
        if media.get("url"):
            return media["url"]
    for link in entry.get("links", []) or []:
        if link.get("type", "").startswith("image/"):
            return link.get("href")
    match = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
    return match.group(1) if match else None


def _categories(entry) -> list[str]:
    return [tag.get("term") for tag in entry.get("tags", []) or [] if tag.get("term")]


async def fetch_feed(source: Source, session: AsyncSession, *, limit: int = 30) -> dict:
    """Читает фид источника и добавляет новые статьи.

    Возвращает сводку: сколько записей в фиде, сколько добавлено, сколько
    статей удалось догрузить целиком.
    """
    feed = await asyncio.to_thread(feedparser.parse, source.url)

    if getattr(feed, "bozo", False) and not feed.entries:
        raise FetchError(f"Не удалось разобрать фид: {getattr(feed, 'bozo_exception', 'неизвестная ошибка')}")

    added = 0
    full_text = 0
    entries = feed.entries[:limit]

    for entry in entries:
        url = entry.get("link")
        title = entry.get("title")
        if not url or not title:
            continue

        exists = await session.scalar(select(Article.id).where(Article.url == url))
        if exists:
            continue

        summary = _strip_html(entry.get("summary", ""))

        # В фиде обычно только анонс — за полным текстом идём на саму страницу.
        # Пауза между статьями: без неё dandavats.com начинает отдавать 429.
        content: str | None = None
        try:
            if added:
                await asyncio.sleep(POLITE_DELAY_SECONDS)
            content = await fetch_article_text(url)
        except FetchError as exc:
            log.warning("Полный текст %s недоступен: %s", url, exc)

        if content and len(content) > len(summary):
            quality = ContentQuality.full
            full_text += 1
        elif summary:
            content = None
            quality = ContentQuality.excerpt
        else:
            quality = ContentQuality.empty

        session.add(
            Article(
                source_id=source.id,
                url=url,
                title=unescape(title).strip(),
                author=entry.get("author"),
                published_at=_parsed_datetime(entry),
                summary=summary or None,
                content=content,
                content_quality=quality,
                image_url=_first_image(entry),
                categories=_categories(entry) or None,
            )
        )
        added += 1

    source.last_fetched_at = datetime.now(timezone.utc)
    source.last_error = None
    await session.commit()

    return {
        "source": source.name,
        "entries": len(entries),
        "added": added,
        "with_full_text": full_text,
    }
