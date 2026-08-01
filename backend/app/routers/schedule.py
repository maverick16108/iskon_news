"""Расписание обхода источников и подписчики бота."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbDep, SuperAdmin, write_audit
from app.models import BotSubscriber, FetchSettings
from app.schemas import (
    BotSubscriberOut,
    FetchSettingsOut,
    FetchSettingsUpdate,
    Message,
)
from app.telegram.bot import collect_summary, render_summary
from app.telegram.config import current as telegram_config
from app.worker import get_fetch_settings, report_new_articles, run_fetch_round

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/schedule", tags=["settings"])


def _out(row: FetchSettings) -> FetchSettingsOut:
    return FetchSettingsOut(
        is_enabled=row.is_enabled,
        interval_minutes=row.interval_minutes,
        min_published_at=row.min_published_at,
        max_age_days=row.max_age_days,
        last_run_at=row.last_run_at,
        last_result=row.last_result,
        last_reported_at=row.last_reported_at,
        updated_at=row.updated_at,
        updated_by=row.updated_by.username if row.updated_by else None,
    )


async def _load(db: DbDep) -> FetchSettings:
    row = await get_fetch_settings(db)
    await db.commit()
    return await db.scalar(
        select(FetchSettings)
        .where(FetchSettings.id == row.id)
        .options(selectinload(FetchSettings.updated_by))
    )


@router.get("", response_model=FetchSettingsOut)
async def get_schedule(db: DbDep, user: CurrentUser):
    return _out(await _load(db))


@router.patch("", response_model=FetchSettingsOut)
async def update_schedule(
    payload: FetchSettingsUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    row = await get_fetch_settings(db)
    changes = payload.model_dump(exclude_unset=True)

    # Ноль в окне равнозначен «не ограничивать»: иначе пришлось бы объяснять,
    # чем «0 дней» отличается от пустого поля
    if changes.get("max_age_days") == 0:
        changes["max_age_days"] = None

    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_by_id = admin.id

    await write_audit(
        db,
        user=admin,
        action="schedule.update",
        entity_type="fetch_settings",
        entity_id=row.id,
        details={k: str(v) for k, v in changes.items()},
        request=request,
    )
    await db.commit()
    return _out(await _load(db))


@router.post("/run", response_model=Message)
async def run_now(request: Request, db: DbDep, user: CurrentUser):
    """Обойти источники прямо сейчас, не дожидаясь расписания."""
    added = await run_fetch_round()
    await report_new_articles()

    await write_audit(
        db,
        user=user,
        action="schedule.run",
        entity_type="fetch_settings",
        entity_id=None,
        details={"добавлено": sum(added.values())},
        request=request,
    )
    await db.commit()

    if not added:
        return Message(detail="Обход завершён, новых публикаций нет")

    parts = ", ".join(f"{name} — {count}" for name, count in added.items())
    return Message(detail=f"Добавлено новостей: {sum(added.values())} ({parts})")


@router.get("/subscribers", response_model=list[BotSubscriberOut])
async def list_subscribers(db: DbDep, admin: SuperAdmin):
    """Кто подписан на оповещения бота."""
    rows = list(
        await db.scalars(select(BotSubscriber).order_by(BotSubscriber.created_at.desc()))
    )
    return [
        BotSubscriberOut(
            id=row.id,
            chat_id=row.chat_id,
            username=row.username,
            full_name=row.full_name,
            notify=row.notify,
            is_blocked=row.is_blocked,
            created_at=row.created_at,
            last_notified_at=row.last_notified_at,
        )
        for row in rows
    ]


@router.post("/subscribers/{subscriber_id}/test", response_model=Message)
async def send_test(subscriber_id: int, db: DbDep, admin: SuperAdmin):
    """Отправляет одному подписчику сводку — проверить, что доходит."""
    person = await db.get(BotSubscriber, subscriber_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подписчик не найден")

    config = await telegram_config()
    if not config.token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Токен бота не задан")

    from app.telegram.bot import _send
    from app.telegram.client import TelegramError

    summary = await collect_summary(db)
    try:
        await _send(config.token, person.chat_id, render_summary(summary, after_fetch=False))
    except TelegramError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не доставлено: {exc}") from exc

    return Message(detail=f"Сводка отправлена {person.username or person.chat_id}")


@router.delete("/subscribers/{subscriber_id}", response_model=Message)
async def remove_subscriber(subscriber_id: int, db: DbDep, admin: SuperAdmin):
    person = await db.get(BotSubscriber, subscriber_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подписчик не найден")

    name = person.username or person.chat_id
    await db.delete(person)
    await db.commit()
    # Человек вернётся в список, если снова напишет боту — это не бан
    return Message(detail=f"{name} убран из списка")
