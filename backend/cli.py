#!/usr/bin/env python
"""Служебные команды.

    python cli.py createsuperuser          — завести первого суперадминистратора
    python cli.py seed-sources             — добавить источники по умолчанию
    python cli.py fetch                    — обойти активные источники
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import func, select

from app.db import SessionFactory
from app.models import Role, Source, SourceKind, User
from app.parsers.rss import fetch_feed
from app.security import hash_password, validate_password_strength

# Источники, с которых начинаем. Остальные добавляются через интерфейс.
DEFAULT_SOURCES = [
    {
        "name": "ISKCON News",
        "url": "https://iskconnews.org/feed/",
        "kind": SourceKind.rss,
        "signature_name": "ISKCON News",
        "signature_suffix": "website",
        "fetch_interval_minutes": 60,
    },
    {
        # У Dandavats читаем помесячный архив, а не RSS: в фид попадают
        # ссылки на чужой блогспот с записями лекций вместо статей.
        "name": "Dandavats",
        "url": "https://www.dandavats.com/",
        "kind": SourceKind.archive,
        "signature_name": "Dandavats",
        "signature_suffix": "website",
        "fetch_interval_minutes": 60,
    },
]


async def create_superuser(username: str | None, password: str | None) -> int:
    async with SessionFactory() as db:
        if username is None:
            username = input("Логин: ").strip()
        if not username:
            print("Логин не может быть пустым", file=sys.stderr)
            return 1

        taken = await db.scalar(select(User.id).where(User.username == username))
        if taken:
            print(f"Пользователь «{username}» уже существует", file=sys.stderr)
            return 1

        if password is None:
            password = getpass.getpass("Пароль: ")
            if password != getpass.getpass("Пароль ещё раз: "):
                print("Пароли не совпадают", file=sys.stderr)
                return 1

        if problem := validate_password_strength(password):
            print(problem, file=sys.stderr)
            return 1

        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role=Role.superadmin,
                full_name=None,
            )
        )
        await db.commit()

    print(f"Суперадминистратор «{username}» создан")
    return 0


async def seed_sources() -> int:
    async with SessionFactory() as db:
        added = 0
        for spec in DEFAULT_SOURCES:
            exists = await db.scalar(select(Source.id).where(Source.url == spec["url"]))
            if exists:
                print(f"Уже есть: {spec['name']}")
                continue
            db.add(Source(**spec))
            added += 1
            print(f"Добавлен: {spec['name']} — {spec['url']}")
        await db.commit()

    print(f"Готово, добавлено источников: {added}")
    return 0


async def fetch_all() -> int:
    async with SessionFactory() as db:
        sources = list(await db.scalars(select(Source).where(Source.is_active.is_(True))))
        if not sources:
            print("Активных источников нет. Сначала: python cli.py seed-sources")
            return 1

        for source in sources:
            print(f"\n{source.name} ({source.url})")
            try:
                result = await fetch_feed(source, db)
            except Exception as exc:  # noqa: BLE001 — обход не должен падать на одном источнике
                print(f"  ошибка: {exc}")
                source.last_error = str(exc)
                await db.commit()
                continue
            print(
                f"  записей в фиде: {result['entries']}, "
                f"добавлено: {result['added']}, "
                f"с полным текстом: {result['with_full_text']}"
            )

        total = await db.scalar(select(func.count()).select_from(Source))
        print(f"\nВсего источников в базе: {total}")
    return 0


async def backfill_images(limit: int) -> int:
    """Догружает картинки к статьям, собранным до появления этой возможности."""
    from sqlalchemy.orm import selectinload

    from app.models import Article, ArticleImage, ArticleVideo
    from app.parsers.fetch import FetchError, fetch_html
    from app.parsers.images import ExtractedImage, extract_images
    from app.parsers.videos import extract_videos

    async with SessionFactory() as db:
        articles = list(
            await db.scalars(
                select(Article)
                .options(selectinload(Article.images), selectinload(Article.videos))
                .order_by(Article.published_at.desc().nullslast())
                .limit(limit)
            )
        )
        # Заодно подбираем те, у кого нет роликов: раньше их не собирали вовсе
        todo = [a for a in articles if not a.images or not a.videos]
        print(f"Статей без картинок или роликов: {len(todo)} из {len(articles)}")

        total = 0
        for index, article in enumerate(todo, 1):
            try:
                if index > 1:
                    await asyncio.sleep(1.5)  # не долбим сайт подряд
                html = await fetch_html(article.url)
                images = extract_images(html, article.url)
                videos = extract_videos(html, article.url)
            except FetchError as exc:
                print(f"  [{index}/{len(todo)}] {article.title[:50]}: {exc}")
                continue

            article.videos = [
                ArticleVideo(
                    url=video.url,
                    provider=video.provider,
                    video_id=video.video_id,
                    thumbnail_url=video.thumbnail_url,
                    position=position,
                )
                for position, video in enumerate(videos)
            ]

            # Уже собранные картинки не трогаем: у редактора там свой выбор
            # и загруженные вручную файлы, а переприсваивание списка вдобавок
            # упирается в уникальный ключ (article_id, url).
            added_images = 0
            if not article.images:
                # У записей лекций своих картинок нет — берём обложку ролика
                if not images:
                    images = [
                        ExtractedImage(
                            url=video.thumbnail_url, caption=None, width=None, height=None
                        )
                        for video in videos
                        if video.thumbnail_url
                    ]

                article.images = [
                    ArticleImage(
                        url=image.url,
                        caption=image.caption,
                        width=image.width,
                        height=image.height,
                        position=position,
                        is_selected=position == 0,
                    )
                    for position, image in enumerate(images)
                ]
                added_images = len(images)
                if images and not article.image_url:
                    article.image_url = images[0].url

            total += added_images
            await db.commit()
            print(
                f"  [{index}/{len(todo)}] {article.title[:50]}: "
                f"картинок {added_images}, роликов {len(videos)}"
            )

        print(f"\nВсего добавлено картинок: {total}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Служебные команды проекта")
    sub = parser.add_subparsers(dest="command", required=True)

    su = sub.add_parser("createsuperuser", help="завести суперадминистратора")
    su.add_argument("--username")
    su.add_argument("--password", help="если не указан — будет запрошен скрыто")

    sub.add_parser("seed-sources", help="добавить источники по умолчанию")
    sub.add_parser("fetch", help="обойти активные источники")

    backfill = sub.add_parser("backfill-images", help="догрузить картинки к старым статьям")
    backfill.add_argument("--limit", type=int, default=100)

    args = parser.parse_args()

    if args.command == "createsuperuser":
        return asyncio.run(create_superuser(args.username, args.password))
    if args.command == "seed-sources":
        return asyncio.run(seed_sources())
    if args.command == "fetch":
        return asyncio.run(fetch_all())
    if args.command == "backfill-images":
        return asyncio.run(backfill_images(args.limit))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
