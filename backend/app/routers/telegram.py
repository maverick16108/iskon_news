"""Настройки публикации в Telegram. Доступны только суперадминистратору."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbDep, SuperAdmin, write_audit
from app.models import TelegramChannel, TelegramSettings
from app.schemas import (
    Message,
    TelegramChannelCreate,
    TelegramChannelOut,
    TelegramChannelUpdate,
    TelegramInfo,
    TelegramSettingsOut,
    TelegramSettingsUpdate,
    TelegramState,
)
from app.telegram.client import TelegramError, check_bot, check_channel
from app.telegram.config import ensure_row

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/telegram", tags=["settings"])


def _settings_out(row: TelegramSettings) -> TelegramSettingsOut:
    return TelegramSettingsOut(
        channel=row.channel,
        is_enabled=row.is_enabled,
        token_set=bool(row.bot_token),
        token_hint=row.token_hint,
        updated_at=row.updated_at,
        updated_by=row.updated_by.username if row.updated_by else None,
    )


def _channel_out(row: TelegramChannel) -> TelegramChannelOut:
    return TelegramChannelOut(
        id=row.id,
        chat=row.chat,
        title=row.title,
        is_enabled=row.is_enabled,
        can_post=row.can_post,
        last_status=row.last_status,
        last_checked_at=row.last_checked_at,
    )


async def _load(db: DbDep) -> TelegramSettings:
    row = await ensure_row(db)
    await db.commit()
    return await db.scalar(
        select(TelegramSettings)
        .where(TelegramSettings.id == row.id)
        .options(selectinload(TelegramSettings.channels), selectinload(TelegramSettings.updated_by))
    )


@router.get("", response_model=TelegramSettingsOut)
async def get_settings(db: DbDep, admin: SuperAdmin):
    return _settings_out(await _load(db))


@router.patch("", response_model=TelegramSettingsOut)
async def update_settings(
    payload: TelegramSettingsUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    row = await ensure_row(db)
    changes = payload.model_dump(exclude_unset=True)

    # Пустая строка в токене означает «не менять»: интерфейс показывает
    # только хвост и присылать токен каждый раз незачем.
    if not changes.get("bot_token"):
        changes.pop("bot_token", None)

    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_by_id = admin.id

    await write_audit(
        db,
        user=admin,
        action="telegram.update",
        entity_type="telegram_settings",
        entity_id=row.id,
        details={
            **{k: str(v) for k, v in changes.items() if k != "bot_token"},
            **({"bot_token": "изменён"} if "bot_token" in changes else {}),
        },
        request=request,
    )
    await db.commit()
    return _settings_out(await _load(db))


@router.get("/state", response_model=TelegramState)
async def state(db: DbDep, user: CurrentUser):
    """Уйдёт ли пост в канал. Нужно редактору перед публикацией."""
    row = await _load(db)
    ready = [c for c in row.channels if c.is_enabled and c.can_post]
    blocked = [c for c in row.channels if c.is_enabled and not c.can_post]

    return TelegramState(
        is_enabled=row.is_enabled,
        ready=[c.title or c.chat for c in ready],
        blocked=[c.title or c.chat for c in blocked],
    )


@router.get("/info", response_model=TelegramInfo)
async def info(db: DbDep, admin: SuperAdmin):
    """Кто подключён и куда вещает. Ничего не публикует."""
    row = await _load(db)

    if not row.bot_token:
        return TelegramInfo(
            token_set=False,
            is_enabled=row.is_enabled,
            channels=[_channel_out(c) for c in row.channels],
            message="Токен бота не задан",
        )

    try:
        bot = await check_bot(row.bot_token)
    except TelegramError as exc:
        return TelegramInfo(
            token_set=True,
            is_enabled=row.is_enabled,
            channels=[_channel_out(c) for c in row.channels],
            message=f"Бот не отвечает: {exc}",
        )

    return TelegramInfo(
        token_set=True,
        is_enabled=row.is_enabled,
        bot_username=bot.get("username"),
        bot_name=bot.get("first_name"),
        bot_id=bot.get("id"),
        channels=[_channel_out(c) for c in row.channels],
        message="",
    )


@router.post("/channels", response_model=TelegramChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(
    payload: TelegramChannelCreate, request: Request, db: DbDep, admin: SuperAdmin
):
    row = await ensure_row(db)

    chat = payload.chat.strip()
    taken = await db.scalar(select(TelegramChannel.id).where(TelegramChannel.chat == chat))
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой канал уже добавлен")

    channel = TelegramChannel(settings_id=row.id, chat=chat, is_enabled=True)
    db.add(channel)
    await db.flush()

    # Сразу проверяем: без прав администратора публиковать не получится,
    # и лучше сказать об этом при добавлении, а не при первой публикации.
    if row.bot_token:
        await _refresh(row.bot_token, channel)

    await write_audit(
        db,
        user=admin,
        action="telegram.channel_add",
        entity_type="telegram_channel",
        entity_id=channel.id,
        details={"chat": chat},
        request=request,
    )
    await db.commit()
    await db.refresh(channel)
    return _channel_out(channel)


@router.patch("/channels/{channel_id}", response_model=TelegramChannelOut)
async def update_channel(
    channel_id: int,
    payload: TelegramChannelUpdate,
    request: Request,
    db: DbDep,
    admin: SuperAdmin,
):
    channel = await db.get(TelegramChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Канал не найден")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)

    await write_audit(
        db,
        user=admin,
        action="telegram.channel_update",
        entity_type="telegram_channel",
        entity_id=channel.id,
        details={"chat": channel.chat, "включён": channel.is_enabled},
        request=request,
    )
    await db.commit()
    await db.refresh(channel)
    return _channel_out(channel)


@router.delete("/channels/{channel_id}", response_model=Message)
async def delete_channel(channel_id: int, request: Request, db: DbDep, admin: SuperAdmin):
    channel = await db.get(TelegramChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Канал не найден")

    chat = channel.chat
    await db.delete(channel)
    await write_audit(
        db,
        user=admin,
        action="telegram.channel_delete",
        entity_type="telegram_channel",
        entity_id=channel_id,
        details={"chat": chat},
        request=request,
    )
    await db.commit()
    return Message(detail=f"Канал {chat} убран из списка")


@router.post("/channels/{channel_id}/check", response_model=TelegramChannelOut)
async def check_one(channel_id: int, db: DbDep, admin: SuperAdmin):
    """Проверяет доступ бота к каналу. Ничего не публикует."""
    row = await ensure_row(db)
    channel = await db.get(TelegramChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Канал не найден")
    if not row.bot_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Токен бота не задан")

    await _refresh(row.bot_token, channel)
    await db.commit()
    await db.refresh(channel)
    return _channel_out(channel)


async def _refresh(token: str, channel: TelegramChannel) -> None:
    """Обновляет название канала и права бота в нём."""
    channel.last_checked_at = datetime.now(timezone.utc)
    try:
        result = await check_channel(token, channel.chat)
    except TelegramError as exc:
        channel.can_post = False
        channel.last_status = str(exc)
        return

    channel.title = result.get("title") or channel.title
    channel.can_post = result.get("can_post")

    if result.get("can_post"):
        channel.last_status = "Бот администратор, публикация разрешена"
    elif result.get("member_error"):
        channel.last_status = "Бот не администратор канала — публиковать не сможет"
    else:
        channel.last_status = f"Бот в канале как «{result.get('status')}», права публиковать нет"
