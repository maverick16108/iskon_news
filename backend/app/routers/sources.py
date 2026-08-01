"""Источники новостей. Читать может любой вошедший, менять — суперадминистратор."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbDep, SuperAdmin, write_audit
from app.models import Source
from app.parsers.fetch import FetchError
from app.parsers.rss import fetch_feed
from app.schemas import FetchResult, Message, SourceCreate, SourceOut, SourceUpdate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
async def list_sources(db: DbDep, user: CurrentUser):
    rows = await db.scalars(
        select(Source).options(selectinload(Source.prompt_template)).order_by(Source.created_at)
    )
    return [
        SourceOut(
            **{c.name: getattr(row, c.name) for c in Source.__table__.columns},
            prompt_template_name=row.prompt_template.name if row.prompt_template else None,
        )
        for row in rows
    ]


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(payload: SourceCreate, request: Request, db: DbDep, admin: SuperAdmin):
    exists = await db.scalar(select(Source.id).where(Source.url == payload.url))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Источник с таким адресом уже добавлен")

    source = Source(**payload.model_dump())
    db.add(source)
    await db.flush()

    await write_audit(
        db,
        user=admin,
        action="source.create",
        entity_type="source",
        entity_id=source.id,
        details={"name": source.name, "url": source.url},
        request=request,
    )
    await db.commit()
    await db.refresh(source)
    return source


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int, payload: SourceUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник не найден")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(source, field, value)

    await write_audit(
        db,
        user=admin,
        action="source.update",
        entity_type="source",
        entity_id=source.id,
        details={"name": source.name, **{k: str(v) for k, v in changes.items()}},
        request=request,
    )
    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/{source_id}", response_model=Message)
async def delete_source(source_id: int, request: Request, db: DbDep, admin: SuperAdmin):
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник не найден")

    name = source.name
    await db.delete(source)
    await write_audit(
        db,
        user=admin,
        action="source.delete",
        entity_type="source",
        entity_id=source_id,
        details={"name": name},
        request=request,
    )
    await db.commit()
    return Message(detail=f"Источник «{name}» удалён вместе с его статьями")


@router.post("/{source_id}/fetch", response_model=FetchResult)
async def fetch_source(source_id: int, request: Request, db: DbDep, user: CurrentUser):
    """Собрать новости из источника прямо сейчас."""
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник не найден")

    try:
        result = await fetch_feed(source, db)
    except FetchError as exc:
        source.last_error = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Источник недоступен: {exc}") from exc

    await write_audit(
        db,
        user=user,
        action="source.fetch",
        entity_type="source",
        entity_id=source.id,
        details=result,
        request=request,
    )
    await db.commit()
    return FetchResult(**result)


@router.post("/fetch-all", response_model=list[FetchResult])
async def fetch_all(request: Request, db: DbDep, user: CurrentUser):
    """Обойти все активные источники."""
    sources = list(await db.scalars(select(Source).where(Source.is_active.is_(True))))

    results: list[FetchResult] = []
    for source in sources:
        try:
            results.append(FetchResult(**await fetch_feed(source, db)))
        except FetchError as exc:
            # Один упавший источник не должен останавливать обход остальных
            log.warning("Источник %s недоступен: %s", source.name, exc)
            source.last_error = str(exc)
            await db.commit()
            results.append(FetchResult(source=source.name, entries=0, added=0, with_full_text=0))

    await write_audit(
        db,
        user=user,
        action="source.fetch_all",
        details={"sources": len(sources), "added": sum(r.added for r in results)},
        request=request,
    )
    await db.commit()
    return results
