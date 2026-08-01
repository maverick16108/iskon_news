"""Действующие настройки публикации в Telegram.

Источник правды — строка в базе; значения из .env работают как запасные,
пока через интерфейс ничего не задано.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionFactory
from app.models import TelegramSettings

SINGLETON_ID = 1


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    channel: str
    enabled: bool


async def get_row(db: AsyncSession) -> TelegramSettings | None:
    return await db.scalar(select(TelegramSettings).where(TelegramSettings.id == SINGLETON_ID))


async def ensure_row(db: AsyncSession) -> TelegramSettings:
    row = await get_row(db)
    if row is None:
        row = TelegramSettings(
            id=SINGLETON_ID,
            bot_token=settings.telegram_bot_token or None,
            channel=settings.telegram_channel,
            is_enabled=False,
        )
        db.add(row)
        await db.flush()

        # Канал из .env заводим сразу, чтобы список не был пустым
        from app.models import TelegramChannel

        if settings.telegram_channel:
            db.add(TelegramChannel(settings_id=row.id, chat=settings.telegram_channel))
            await db.flush()
    return row


async def current() -> TelegramConfig:
    """Читаем на каждый вызов: после правки через интерфейс перезапуск не нужен."""
    async with SessionFactory() as db:
        row = await get_row(db)

    if row is None:
        return TelegramConfig(
            token=settings.telegram_bot_token,
            channel=settings.telegram_channel,
            enabled=False,
        )

    return TelegramConfig(
        token=row.bot_token or settings.telegram_bot_token,
        channel=row.channel or settings.telegram_channel,
        enabled=row.is_enabled,
    )
