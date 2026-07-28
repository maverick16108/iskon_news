"""Зависимости FastAPI: текущий пользователь, проверка прав, журналирование."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import AuditLog, Session as DbSession, User
from app.security import SESSION_COOKIE

DbDep = Annotated[AsyncSession, Depends(get_db)]


async def current_user(
    db: DbDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему")

    row = await db.scalar(
        select(DbSession)
        .where(DbSession.id == session_token)
        .options(selectinload(DbSession.user))
    )

    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия не найдена, войдите заново")

    if row.expires_at <= datetime.now(timezone.utc):
        await db.execute(delete(DbSession).where(DbSession.id == row.id))
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите заново")

    if not row.user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена")

    return row.user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_superadmin(user: CurrentUser) -> User:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Действие доступно только суперадминистратору")
    return user


SuperAdmin = Annotated[User, Depends(require_superadmin)]


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def write_audit(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip=client_ip(request) if request else None,
        )
    )
