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
from app.models import (
    DEFAULT_MIN_POST_CHARS,
    MAX_POST_CHARS,
    LlmSettings,
    PromptTemplate,
    Source,
)

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


@dataclass(frozen=True)
class ResolvedPrompt:
    """Шаблон, по которому перерабатывается новость этого источника."""

    body: str | None          # None — собрать встроенный шаблон
    min_chars: int
    max_chars: int


async def prompt_for(source: Source | None) -> ResolvedPrompt:
    """Какой шаблон применяется к источнику и в какую длину укладывать пост.

    Порядок такой: свой шаблон источника, затем помеченный «по умолчанию»,
    и лишь потом встроенный. Средняя ступень тут обязательна — именно её
    обещает интерфейс («применяется к источникам, которым свой шаблон
    не назначен»), и без неё правки шаблона в базе никуда не доходили бы.
    """
    template = source.prompt_template if source is not None else None

    if template is None:
        async with SessionFactory() as db:
            template = await db.scalar(
                select(PromptTemplate).where(PromptTemplate.is_default.is_(True)).limit(1)
            )

    if template is None:
        return ResolvedPrompt(None, DEFAULT_MIN_POST_CHARS, MAX_POST_CHARS)

    return ResolvedPrompt(template.body, template.post_min_chars, template.post_max_chars)


async def remember_outcome(error: str | None, *, out_of_money: bool = False) -> None:
    """Запоминает, чем закончилось обращение к модели.

    Баланс счёта OpenAI через API не отдаёт: узнать, что деньги кончились,
    можно только по отказу. Поэтому храним сам отказ — иначе в настройках
    подключение выглядело бы исправным, пока кто-нибудь не нажмёт кнопку.
    """
    from datetime import datetime, timezone

    from app.db import SessionFactory
    from app.models import LlmSettings

    async with SessionFactory() as db:
        row = await db.scalar(select(LlmSettings).limit(1))
        if row is None:
            return

        now = datetime.now(timezone.utc)
        if error is None:
            row.last_ok_at = now
            row.last_error = None
            row.last_error_at = None
            row.out_of_money = False
        else:
            row.last_error = error
            row.last_error_at = now
            row.out_of_money = out_of_money

        await db.commit()
