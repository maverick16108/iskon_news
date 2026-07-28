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
        "name": "Dandavats",
        "url": "https://www.dandavats.com/?feed=rss2",
        "kind": SourceKind.rss,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Служебные команды проекта")
    sub = parser.add_subparsers(dest="command", required=True)

    su = sub.add_parser("createsuperuser", help="завести суперадминистратора")
    su.add_argument("--username")
    su.add_argument("--password", help="если не указан — будет запрошен скрыто")

    sub.add_parser("seed-sources", help="добавить источники по умолчанию")
    sub.add_parser("fetch", help="обойти активные источники")

    args = parser.parse_args()

    if args.command == "createsuperuser":
        return asyncio.run(create_superuser(args.username, args.password))
    if args.command == "seed-sources":
        return asyncio.run(seed_sources())
    if args.command == "fetch":
        return asyncio.run(fetch_all())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
