from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DbDep, SuperAdmin
from app.models import AuditLog
from app.schemas import AuditOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
async def list_audit(
    db: DbDep,
    admin: SuperAdmin,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
    )
    if action:
        query = query.where(AuditLog.action == action)

    rows = list(await db.scalars(query.limit(limit).offset(offset)))

    return [
        AuditOut(
            id=row.id,
            user_id=row.user_id,
            username=row.user.username if row.user else None,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            details=row.details,
            ip=row.ip,
            created_at=row.created_at,
        )
        for row in rows
    ]
