"""Площадки публикации: Telegram, MAX. Настраивает суперадминистратор."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbDep, SuperAdmin, write_audit
from app.models import Platform, PlatformKind, TelegramChannel
from app.publishers import max as max_api
from app.schemas import (
    ChannelCreate,
    ChannelOut,
    ChannelUpdate,
    Message,
    PlatformCreate,
    PlatformOut,
    PlatformUpdate,
)
from app.telegram.client import TelegramError, check_bot, check_channel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/platforms", tags=["settings"])


def _channel_out(row: TelegramChannel) -> ChannelOut:
    return ChannelOut(
        id=row.id,
        platform_id=row.platform_id,
        chat=row.chat,
        title=row.title,
        is_enabled=row.is_enabled,
        can_post=row.can_post,
        last_status=row.last_status,
        last_checked_at=row.last_checked_at,
    )


def _out(row: Platform) -> PlatformOut:
    return PlatformOut(
        id=row.id,
        kind=row.kind,
        title=row.title,
        is_enabled=row.is_enabled,
        token_set=bool(row.token),
        token_hint=row.token_hint,
        bot_username=row.bot_username,
        bot_id=row.bot_id,
        last_status=row.last_status,
        last_checked_at=row.last_checked_at,
        channels=[_channel_out(c) for c in row.channels],
    )


async def _load_all(db: DbDep) -> list[Platform]:
    return list(
        await db.scalars(
            select(Platform).options(selectinload(Platform.channels)).order_by(Platform.id)
        )
    )


async def _get(db: DbDep, platform_id: int) -> Platform:
    row = await db.scalar(
        select(Platform)
        .where(Platform.id == platform_id)
        .options(selectinload(Platform.channels))
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Площадка не найдена")
    return row


@router.get("", response_model=list[PlatformOut])
async def list_platforms(db: DbDep, user: CurrentUser):
    return [_out(row) for row in await _load_all(db)]


@router.post("", response_model=PlatformOut, status_code=status.HTTP_201_CREATED)
async def create_platform(
    payload: PlatformCreate, request: Request, db: DbDep, admin: SuperAdmin
):
    platform = Platform(
        kind=payload.kind,
        title=payload.title.strip(),
        token=payload.token.strip() or None,
        is_enabled=False,   # включают отдельно, уже проверив связь
        updated_by_id=admin.id,
    )
    db.add(platform)
    await db.flush()

    # Сразу проверяем токен: лучше сказать о нерабочем ключе при добавлении,
    # чем при первой публикации
    if platform.token:
        await _refresh_bot(platform)

    await write_audit(
        db,
        user=admin,
        action="platform.create",
        entity_type="platform",
        entity_id=platform.id,
        details={"kind": platform.kind.value, "title": platform.title},
        request=request,
    )
    await db.commit()
    return _out(await _get(db, platform.id))


@router.patch("/{platform_id}", response_model=PlatformOut)
async def update_platform(
    platform_id: int, payload: PlatformUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    platform = await _get(db, platform_id)
    changes = payload.model_dump(exclude_unset=True)

    # Пустая строка в токене означает «не менять»: наружу мы отдаём
    # только хвост, и присылать его целиком каждый раз незачем
    if not changes.get("token"):
        changes.pop("token", None)

    for field, value in changes.items():
        setattr(platform, field, value)
    platform.updated_by_id = admin.id

    if "token" in changes:
        await _refresh_bot(platform)

    await write_audit(
        db,
        user=admin,
        action="platform.update",
        entity_type="platform",
        entity_id=platform.id,
        details={
            **{k: str(v) for k, v in changes.items() if k != "token"},
            **({"token": "изменён"} if "token" in changes else {}),
        },
        request=request,
    )
    await db.commit()
    return _out(await _get(db, platform_id))


@router.delete("/{platform_id}", response_model=Message)
async def delete_platform(platform_id: int, request: Request, db: DbDep, admin: SuperAdmin):
    platform = await _get(db, platform_id)
    title = platform.title

    await db.delete(platform)
    await write_audit(
        db,
        user=admin,
        action="platform.delete",
        entity_type="platform",
        entity_id=platform_id,
        details={"title": title},
        request=request,
    )
    await db.commit()
    return Message(detail=f"Площадка «{title}» удалена вместе со своими каналами")


@router.post("/{platform_id}/check", response_model=PlatformOut)
async def check_platform(platform_id: int, db: DbDep, admin: SuperAdmin):
    """Проверяет токен площадки. Ничего не публикует."""
    platform = await _get(db, platform_id)
    if not platform.token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Токен не задан")

    await _refresh_bot(platform)
    await db.commit()
    return _out(await _get(db, platform_id))


# --- Каналы площадки -------------------------------------------------------


@router.post(
    "/{platform_id}/channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED
)
async def add_channel(
    platform_id: int, payload: ChannelCreate, request: Request, db: DbDep, admin: SuperAdmin
):
    platform = await _get(db, platform_id)

    chat = payload.chat.strip()
    taken = await db.scalar(select(TelegramChannel.id).where(TelegramChannel.chat == chat))
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой канал уже добавлен")

    channel = TelegramChannel(platform_id=platform.id, settings_id=1, chat=chat, is_enabled=True)
    db.add(channel)
    await db.flush()

    if platform.token:
        await _refresh_channel(platform, channel)

    await write_audit(
        db,
        user=admin,
        action="platform.channel_add",
        entity_type="telegram_channel",
        entity_id=channel.id,
        details={"chat": chat, "platform": platform.title},
        request=request,
    )
    await db.commit()
    await db.refresh(channel)
    return _channel_out(channel)


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: int, payload: ChannelUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    channel = await db.get(TelegramChannel, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Канал не найден")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)

    await write_audit(
        db,
        user=admin,
        action="platform.channel_update",
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
        action="platform.channel_delete",
        entity_type="telegram_channel",
        entity_id=channel_id,
        details={"chat": chat},
        request=request,
    )
    await db.commit()
    return Message(detail=f"Канал {chat} убран из списка")


@router.post("/channels/{channel_id}/check", response_model=ChannelOut)
async def check_one_channel(channel_id: int, db: DbDep, admin: SuperAdmin):
    channel = await db.scalar(
        select(TelegramChannel)
        .where(TelegramChannel.id == channel_id)
        .options(selectinload(TelegramChannel.platform))
    )
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Канал не найден")
    if channel.platform is None or not channel.platform.token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У площадки не задан токен")

    await _refresh_channel(channel.platform, channel)
    await db.commit()
    await db.refresh(channel)
    return _channel_out(channel)


# --- Проверки --------------------------------------------------------------


async def _refresh_bot(platform: Platform) -> None:
    """Кто подключён по этому токену. Ничего не публикует."""
    platform.last_checked_at = datetime.now(timezone.utc)
    try:
        if platform.kind is PlatformKind.telegram:
            bot = await check_bot(platform.token)
            platform.bot_username = bot.get("username")
            platform.bot_id = str(bot.get("id") or "") or None
        else:
            bot = await max_api.check_bot(platform.token)
            platform.bot_username = bot.get("username") or bot.get("name")
            platform.bot_id = str(bot.get("user_id") or bot.get("id") or "") or None
        platform.last_status = "Токен работает, бот на связи"
    except (TelegramError, max_api.MaxError) as exc:
        platform.bot_username = None
        platform.bot_id = None
        platform.last_status = f"Бот не отвечает: {exc}"


async def _refresh_channel(platform: Platform, channel: TelegramChannel) -> None:
    """Название канала и права бота в нём."""
    channel.last_checked_at = datetime.now(timezone.utc)
    try:
        if platform.kind is PlatformKind.telegram:
            result = await check_channel(platform.token, channel.chat)
        else:
            result = await max_api.check_channel(platform.token, channel.chat)
    except (TelegramError, max_api.MaxError) as exc:
        channel.can_post = False
        channel.last_status = str(exc)
        return

    channel.title = result.get("title") or channel.title
    channel.can_post = result.get("can_post")

    if result.get("can_post"):
        channel.last_status = "Бот администратор, публикация разрешена"
    elif result.get("member_error"):
        channel.last_status = f"Бот не может писать в канал: {result['member_error']}"
    else:
        channel.last_status = f"Бот в канале как «{result.get('status')}», права публиковать нет"
