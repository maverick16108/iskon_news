"""Настройки публикации в Telegram. Доступны только суперадминистратору."""

import logging

from fastapi import APIRouter, Request

from app.deps import DbDep, SuperAdmin, write_audit
from app.schemas import TelegramCheckResult, TelegramSettingsOut, TelegramSettingsUpdate
from app.telegram.client import TelegramError, check
from app.telegram.config import ensure_row

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/telegram", tags=["settings"])


def _to_out(row) -> TelegramSettingsOut:
    return TelegramSettingsOut(
        channel=row.channel,
        is_enabled=row.is_enabled,
        token_set=bool(row.bot_token),
        token_hint=row.token_hint,
        updated_at=row.updated_at,
        updated_by=row.updated_by.username if row.updated_by else None,
    )


@router.get("", response_model=TelegramSettingsOut)
async def get_settings(db: DbDep, admin: SuperAdmin):
    row = await ensure_row(db)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


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
    await db.refresh(row)
    return _to_out(row)


@router.post("/check", response_model=TelegramCheckResult)
async def check_connection(db: DbDep, admin: SuperAdmin):
    """Проверяет бота и доступ к каналу. Ничего не публикует."""
    row = await ensure_row(db)
    await db.commit()

    if not row.bot_token:
        return TelegramCheckResult(ok=False, message="Токен бота не задан")

    try:
        info = await check(row.bot_token, row.channel)
    except TelegramError as exc:
        return TelegramCheckResult(ok=False, message=str(exc))

    bot = info.get("bot")

    if info.get("channel_error"):
        return TelegramCheckResult(
            ok=False,
            bot=bot,
            message=f"Бот @{bot} на связи, но канал {row.channel} недоступен: "
            f"{info['channel_error']}",
        )

    if info.get("can_post"):
        return TelegramCheckResult(
            ok=True,
            bot=bot,
            channel_title=info.get("channel_title"),
            can_post=True,
            message=f"Бот @{bot} — администратор канала «{info.get('channel_title')}» "
            "с правом публикации. Всё готово.",
        )

    return TelegramCheckResult(
        ok=False,
        bot=bot,
        channel_title=info.get("channel_title"),
        can_post=False,
        message=(
            f"Бот @{bot} видит канал «{info.get('channel_title')}», но публиковать не может. "
            f"Добавьте @{bot} администратором канала с правом «Публикация сообщений»."
        ),
    )
