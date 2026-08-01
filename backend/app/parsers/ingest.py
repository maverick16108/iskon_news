"""Общая часть сбора: превращение найденных ссылок в статьи.

RSS и помесячный архив различаются только тем, откуда берётся список
публикаций. Всё, что дальше — проверка на дубли, догрузка полного текста,
извлечение картинок, — общее, и живёт здесь.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Article,
    ArticleImage,
    ArticleMention,
    ArticleVideo,
    ContentQuality,
    Source,
    title_key_for,
)
from app.parsers.fetch import FetchError, extract_text, fetch_html
from app.parsers.images import extract_images
from app.parsers.videos import extract_videos

log = logging.getLogger(__name__)

# Пауза между запросами к статьям одного источника: без неё
# dandavats.com начинает отдавать 429.
POLITE_DELAY_SECONDS = 1.5

# Ниже этого объёма считаем, что полноценного текста нет.
# Сравнивать с длиной анонса нельзя: у некоторых источников анонс в RSS
# длиннее иной статьи, и нормально извлечённый текст не проходил проверку.
MIN_FULL_TEXT_CHARS = 400


@dataclass
class FoundPost:
    """Публикация, найденная в фиде или архиве."""

    url: str
    title: str
    published_at: datetime | None = None
    summary: str | None = None
    author: str | None = None
    categories: list[str] | None = None
    fallback_image: str | None = None


@dataclass
class IngestResult:
    entries: int = 0
    added: int = 0
    with_full_text: int = 0
    images: int = 0
    videos: int = 0
    repeats: int = 0            # уже были в ленте от другого источника
    skipped_boilerplate: int = 0
    _seen_texts: set[str] = field(default_factory=set, repr=False)

    def as_dict(self, source_name: str) -> dict:
        return {
            "source": source_name,
            "entries": self.entries,
            "added": self.added,
            "with_full_text": self.with_full_text,
            "images": self.images,
            "videos": self.videos,
            "repeats": self.repeats,
        }


async def _remember_mention(
    session: AsyncSession, article_id: int, source_id: int, url: str
) -> bool:
    """Отмечает, что источник принёс эту новость. True, если отметка новая."""
    result = await session.execute(
        pg_insert(ArticleMention)
        .values(article_id=article_id, source_id=source_id, url=url)
        .on_conflict_do_nothing(constraint="uq_article_mention")
    )
    return result.rowcount > 0


async def ingest(
    source: Source, session: AsyncSession, posts: list[FoundPost], *, limit: int
) -> IngestResult:
    result = IngestResult(entries=len(posts))
    posts = posts[:limit]

    # Тексты уже добавленных в этот заход — чтобы поймать обвязку сайта,
    # которая у всех страниц источника одинаковая.
    fetched_count = 0

    for post in posts:
        exists = await session.scalar(select(Article.id).where(Article.url == post.url))
        if exists:
            # Новость уже есть — но пришла ещё и отсюда. Дайджест ISKCON
            # Connection ссылается на dandavats напрямую, и почти весь его
            # улов такой. Заводить второй экземпляр незачем, а отметить,
            # что источников несколько, нужно.
            if await _remember_mention(session, exists, source.id, post.url):
                result.repeats += 1
            continue

        content: str | None = None
        images: list = []
        videos: list = []
        try:
            if fetched_count:
                await asyncio.sleep(POLITE_DELAY_SECONDS)
            html = await fetch_html(post.url)
            fetched_count += 1
            content = extract_text(html)
            images = extract_images(html, post.url)
            videos = extract_videos(html, post.url)
        except FetchError as exc:
            log.warning("Полный текст %s недоступен: %s", post.url, exc)

        # Одинаковый текст у разных статей одного источника — верный признак,
        # что вытащили меню или боковую колонку, а не материал.
        if content and content.strip() in result._seen_texts:
            log.info("У %s текст совпал с предыдущей статьёй — считаем обвязкой", post.url)
            content = None
            result.skipped_boilerplate += 1
        elif content:
            result._seen_texts.add(content.strip())

        if content and len(content) >= MIN_FULL_TEXT_CHARS:
            quality = ContentQuality.full
            result.with_full_text += 1
        elif post.summary:
            content = None
            quality = ContentQuality.excerpt
        else:
            content = None
            quality = ContentQuality.empty

        article = Article(
            source_id=source.id,
            url=post.url,
            title=post.title.strip(),
            title_key=title_key_for(post.title),
            author=post.author,
            published_at=post.published_at,
            summary=post.summary,
            content=content,
            content_quality=quality,
            image_url=images[0].url if images else post.fallback_image,
            categories=post.categories,
        )
        # Первую картинку отмечаем сразу: в посте почти всегда нужна хотя бы одна
        article.images = [
            ArticleImage(
                url=image.url,
                caption=image.caption,
                width=image.width,
                height=image.height,
                position=index,
                is_selected=index == 0,
            )
            for index, image in enumerate(images)
        ]
        article.videos = [
            ArticleVideo(
                url=video.url,
                provider=video.provider,
                video_id=video.video_id,
                thumbnail_url=video.thumbnail_url,
                position=index,
            )
            for index, video in enumerate(videos)
        ]

        # Обложки роликов кладём в галерею всегда, а не только когда своих
        # картинок нет: для новости с видео она часто и есть самая говорящая
        # иллюстрация, и редактор должен иметь возможность её выбрать.
        seen_urls = {image.url for image in article.images}
        position = len(article.images)
        for video in videos:
            if not video.thumbnail_url or video.thumbnail_url in seen_urls:
                continue
            seen_urls.add(video.thumbnail_url)
            article.images.append(
                ArticleImage(
                    url=video.thumbnail_url,
                    caption=None,
                    position=position,
                    # Отмечаем только если других картинок не нашлось —
                    # иначе пост уйдёт без иллюстрации вовсе
                    is_selected=not images and position == 0,
                    from_video=True,
                )
            )
            position += 1

        # Главная — первая отмеченная
        for image in article.images:
            if image.is_selected:
                image.is_cover = True
                break

        if not article.image_url and article.images:
            article.image_url = article.images[0].url

        session.add(article)
        await session.flush()
        await _remember_mention(session, article.id, source.id, post.url)
        result.added += 1
        result.images += len(images)
        result.videos += len(videos)

    source.last_fetched_at = datetime.now(timezone.utc)
    source.last_error = None
    await session.commit()

    if result.skipped_boilerplate:
        log.info(
            "%s: у %d статей текст оказался обвязкой сайта",
            source.name,
            result.skipped_boilerplate,
        )
    return result
