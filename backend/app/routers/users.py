"""Управление пользователями. Всё внутри доступно только суперадминистратору."""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, func, select

from app.deps import DbDep, SuperAdmin, write_audit
from app.models import Session as DbSession, Role, User
from app.schemas import Message, UserCreate, UserOut, UserUpdate
from app.security import hash_password, validate_password_strength

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(db: DbDep, admin: SuperAdmin):
    result = await db.scalars(select(User).order_by(User.created_at.desc()))
    return list(result)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, request: Request, db: DbDep, admin: SuperAdmin):
    taken = await db.scalar(select(User.id).where(User.username == payload.username))
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой логин уже занят")

    if problem := validate_password_strength(payload.password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        created_by_id=admin.id,
    )
    db.add(user)
    await db.flush()

    await write_audit(
        db,
        user=admin,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        details={"username": user.username, "role": user.role.value},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, payload: UserUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    changes: dict[str, object] = {}

    if payload.full_name is not None:
        user.full_name = payload.full_name
        changes["full_name"] = payload.full_name

    if payload.role is not None and payload.role is not user.role:
        # Нельзя разжаловать самого себя и остаться без суперадминистратора
        if user.id == admin.id and payload.role is not Role.superadmin:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя снять с себя права суперадминистратора")
        await _ensure_superadmin_remains(db, user, new_role=payload.role)
        user.role = payload.role
        changes["role"] = payload.role.value

    if payload.is_active is not None and payload.is_active != user.is_active:
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя отключить собственную учётную запись")
        if not payload.is_active:
            await _ensure_superadmin_remains(db, user, new_role=None)
            # Отключили — рвём активные сессии, иначе человек продолжит работать
            await db.execute(delete(DbSession).where(DbSession.user_id == user.id))
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active

    if payload.password is not None:
        if problem := validate_password_strength(payload.password):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
        user.password_hash = hash_password(payload.password)
        # Смена пароля завершает все прочие сессии этого пользователя
        await db.execute(delete(DbSession).where(DbSession.user_id == user.id))
        changes["password"] = "изменён"

    await write_audit(
        db,
        user=admin,
        action="user.update",
        entity_type="user",
        entity_id=user.id,
        details={"username": user.username, **changes},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=Message)
async def delete_user(user_id: int, request: Request, db: DbDep, admin: SuperAdmin):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя удалить собственную учётную запись")

    await _ensure_superadmin_remains(db, user, new_role=None)

    username = user.username
    await db.delete(user)
    await write_audit(
        db,
        user=admin,
        action="user.delete",
        entity_type="user",
        entity_id=user_id,
        details={"username": username},
        request=request,
    )
    await db.commit()
    return Message(detail=f"Пользователь {username} удалён")


async def _ensure_superadmin_remains(db: DbDep, target: User, *, new_role: Role | None) -> None:
    """Не даёт остаться без единого действующего суперадминистратора."""
    if target.role is not Role.superadmin:
        return
    if new_role is Role.superadmin:
        return

    others = await db.scalar(
        select(func.count(User.id)).where(
            User.role == Role.superadmin,
            User.is_active.is_(True),
            User.id != target.id,
        )
    )
    if not others:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Это последний активный суперадминистратор — сначала назначьте другого",
        )
