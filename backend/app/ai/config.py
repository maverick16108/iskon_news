"""Действующие настройки подключения к языковой модели.

Источник правды — строка в базе. Пока её нет, работаем по значениям из .env,
чтобы приложение поднималось без предварительной настройки через интерфейс.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionFactory
from app.models import LlmSettings

SINGLETON_ID = 1


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float


async def get_row(db: AsyncSession) -> LlmSettings | None:
    return await db.scalar(select(LlmSettings).where(LlmSettings.id == SINGLETON_ID))


async def ensure_row(db: AsyncSession) -> LlmSettings:
    """Возвращает строку настроек, при первом обращении создавая её из .env."""
    row = await get_row(db)
    if row is None:
        row = LlmSettings(
            id=SINGLETON_ID,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key or None,
            model=settings.openai_model,
            temperature=0.4,
        )
        db.add(row)
        await db.flush()
    return row


async def current() -> LlmConfig:
    """Настройки для очередного обращения к модели.

    Читаем на каждый вызов, а не кэшируем: иначе после правки через интерфейс
    пришлось бы перезапускать сервис.
    """
    async with SessionFactory() as db:
        row = await get_row(db)

    if row is None:
        return LlmConfig(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0.4,
        )

    return LlmConfig(
        base_url=row.base_url or settings.openai_base_url,
        api_key=row.api_key or settings.openai_api_key,
        model=row.model or settings.openai_model,
        temperature=row.temperature,
    )
