"""Сбор новостей из источника: RSS-фид или помесячный архив."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from html import unescape

import feedparser
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceKind
from app.parsers.archive import collect_posts
from app.parsers.newsletter import collect_posts as collect_newsletter
from app.parsers.fetch import FetchError
from app.parsers.ingest import FoundPost, fetch_cutoff, ingest

log = logging.getLogger(__name__)

# Хвост, который WordPress дописывает к анонсу в фиде
WP_TAIL = re.compile(r"The post .*? appeared first on .*?\.\s*$", re.S)


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


async def _posts_from_feed(source: Source) -> list[FoundPost]:
    feed = await asyncio.to_thread(feedparser.parse, source.url)

    if getattr(feed, "bozo", False) and not feed.entries:
        raise FetchError(
            f"Не удалось разобрать фид: {getattr(feed, 'bozo_exception', 'неизвестная ошибка')}"
        )

    posts: list[FoundPost] = []
    for entry in feed.entries:
        url, title = entry.get("link"), entry.get("title")
        if not url or not title:
            continue
        posts.append(
            FoundPost(
                url=url,
                title=unescape(title),
                published_at=_parsed_datetime(entry),
                summary=_strip_html(entry.get("summary", "")) or None,
                author=entry.get("author"),
                categories=_categories(entry) or None,
                fallback_image=_first_image(entry),
            )
        )
    return posts


async def _posts_from_archive(source: Source) -> list[FoundPost]:
    # Два месяца: столько dandavats отдаёт без отказов. Более глубокая
    # история добирается отдельным медленным заданием (cli.py slow-sync),
    # а не каждым часовым обходом: полгода — это 48 страниц списка за раз,
    # и сайт начинает отвечать 429 ещё до статей.
    found = await collect_posts(source.url, months_back=2, limit=120)
    return [
        FoundPost(url=post.url, title=post.title, published_at=post.published_at)
        for post in found
    ]


async def _posts_from_newsletter(source: Source) -> list[FoundPost]:
    found = await collect_newsletter(source.url, issues_back=4, limit=200)
    return [
        FoundPost(url=post.url, title=post.title, published_at=post.published_at)
        for post in found
    ]


async def fetch_feed(source: Source, session: AsyncSession, *, limit: int = 40) -> dict:
    """Читает источник и добавляет новые статьи.

    Возвращает сводку: сколько публикаций найдено, сколько добавлено,
    у скольких удалось получить полный текст и сколько картинок собрано.
    """
    if source.kind is SourceKind.archive:
        posts = await _posts_from_archive(source)
    elif source.kind is SourceKind.newsletter:
        posts = await _posts_from_newsletter(source)
    else:
        posts = await _posts_from_feed(source)

    result = await ingest(
        source, session, posts, limit=limit, not_older_than=await fetch_cutoff(session)
    )
    return result.as_dict(source.name)
