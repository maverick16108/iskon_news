"""Шаблоны промптов. Читать может любой вошедший, менять — суперадминистратор."""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.ai.prompt import DEFAULT_TEMPLATE, PLACEHOLDERS, render_system_prompt
from app.deps import CurrentUser, DbDep, SuperAdmin, write_audit
from app.models import PromptTemplate, Source
from app.schemas import (
    Message,
    PromptOut,
    PromptCreate,
    PromptPreview,
    PromptUpdate,
    PlaceholderInfo,
)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _to_out(row: PromptTemplate, used_by: int = 0) -> PromptOut:
    return PromptOut(
        id=row.id,
        name=row.name,
        description=row.description,
        body=row.body,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
        updated_by=row.updated_by.username if row.updated_by else None,
        used_by_sources=used_by,
    )


async def ensure_seeded(db: DbDep) -> None:
    """При первом обращении заводит шаблон по умолчанию из встроенного."""
    exists = await db.scalar(select(func.count(PromptTemplate.id)))
    if exists:
        return

    db.add(
        PromptTemplate(
            name="Новости ИСККОН — базовый",
            description="Перевод на русский и сжатие в пост канала. Используется, если источнику не назначен свой шаблон.",
            body=DEFAULT_TEMPLATE,
            is_default=True,
        )
    )
    await db.commit()


@router.get("/placeholders", response_model=list[PlaceholderInfo])
async def list_placeholders(user: CurrentUser):
    """Что можно подставить в шаблон."""
    return [PlaceholderInfo(token=token, description=text) for token, text in PLACEHOLDERS.items()]


@router.get("", response_model=list[PromptOut])
async def list_prompts(db: DbDep, user: CurrentUser):
    await ensure_seeded(db)

    rows = list(
        await db.scalars(
            select(PromptTemplate)
            .options(selectinload(PromptTemplate.updated_by), selectinload(PromptTemplate.sources))
            .order_by(PromptTemplate.is_default.desc(), PromptTemplate.name)
        )
    )
    return [_to_out(row, len(row.sources)) for row in rows]


@router.post("", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
async def create_prompt(payload: PromptCreate, request: Request, db: DbDep, admin: SuperAdmin):
    taken = await db.scalar(select(PromptTemplate.id).where(PromptTemplate.name == payload.name))
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Шаблон с таким названием уже есть")

    prompt = PromptTemplate(**payload.model_dump(), updated_by_id=admin.id)
    db.add(prompt)
    await db.flush()

    if prompt.is_default:
        await _clear_other_defaults(db, prompt.id)

    await write_audit(
        db,
        user=admin,
        action="prompt.create",
        entity_type="prompt",
        entity_id=prompt.id,
        details={"name": prompt.name},
        request=request,
    )
    await db.commit()
    await db.refresh(prompt)
    return _to_out(prompt)


@router.patch("/{prompt_id}", response_model=PromptOut)
async def update_prompt(
    prompt_id: int, payload: PromptUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    prompt = await db.get(PromptTemplate, prompt_id)
    if prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не найден")

    changes = payload.model_dump(exclude_unset=True)

    if "is_default" in changes and not changes["is_default"] and prompt.is_default:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Нельзя снять признак «по умолчанию» — назначьте его другому шаблону",
        )

    for field, value in changes.items():
        setattr(prompt, field, value)
    prompt.updated_by_id = admin.id

    if changes.get("is_default"):
        await _clear_other_defaults(db, prompt.id)

    await write_audit(
        db,
        user=admin,
        action="prompt.update",
        entity_type="prompt",
        entity_id=prompt.id,
        details={"name": prompt.name, "поля": ", ".join(changes)},
        request=request,
    )
    await db.commit()
    await db.refresh(prompt)
    return _to_out(prompt)


@router.delete("/{prompt_id}", response_model=Message)
async def delete_prompt(prompt_id: int, request: Request, db: DbDep, admin: SuperAdmin):
    prompt = await db.scalar(
        select(PromptTemplate)
        .where(PromptTemplate.id == prompt_id)
        .options(selectinload(PromptTemplate.sources))
    )
    if prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не найден")

    if prompt.is_default:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Это шаблон по умолчанию — сначала назначьте другой",
        )
    if prompt.sources:
        names = ", ".join(source.name for source in prompt.sources)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Шаблон используют источники: {names}. Сначала переназначьте их.",
        )

    name = prompt.name
    await db.delete(prompt)
    await write_audit(
        db,
        user=admin,
        action="prompt.delete",
        entity_type="prompt",
        entity_id=prompt_id,
        details={"name": name},
        request=request,
    )
    await db.commit()
    return Message(detail=f"Шаблон «{name}» удалён")


@router.post("/preview", response_model=PromptPreview)
async def preview_prompt(payload: PromptCreate, user: CurrentUser):
    """Показывает промпт целиком — с подставленными списками и блоком формата."""
    rendered = render_system_prompt(payload.body)
    return PromptPreview(rendered=rendered, chars=len(rendered))


async def _clear_other_defaults(db: DbDep, keep_id: int) -> None:
    others = await db.scalars(
        select(PromptTemplate).where(
            PromptTemplate.is_default.is_(True), PromptTemplate.id != keep_id
        )
    )
    for row in others:
        row.is_default = False
