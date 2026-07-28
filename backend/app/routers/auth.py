from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from app.config import settings
from app.deps import CurrentUser, DbDep, client_ip, write_audit
from app.models import Session as DbSession, User
from app.schemas import LoginRequest, Message, UserOut
from app.security import (
    SESSION_COOKIE,
    new_session_token,
    session_expiry,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(payload: LoginRequest, request: Request, response: Response, db: DbDep):
    user = await db.scalar(select(User).where(User.username == payload.username))

    # Одинаковый ответ на «нет такого пользователя» и «неверный пароль»,
    # чтобы по ответу нельзя было перебирать существующие логины.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

    if user is None or not verify_password(payload.password, user.password_hash):
        raise invalid
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена")

    token = new_session_token()
    db.add(
        DbSession(
            id=token,
            user_id=user.id,
            expires_at=session_expiry(settings.session_ttl_seconds),
            user_agent=request.headers.get("user-agent", "")[:512],
            ip=client_ip(request),
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    await write_audit(db, user=user, action="login", request=request)
    await db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,  # недоступна из JavaScript — защита от кражи через XSS
        samesite="lax",
        secure=settings.cookie_secure,  # под HTTPS включается через COOKIE_SECURE=true
        path="/",
    )
    return user


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, db: DbDep, user: CurrentUser):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(DbSession).where(DbSession.id == token))
    await write_audit(db, user=user, action="logout", request=request)
    await db.commit()

    response.delete_cookie(SESSION_COOKIE, path="/")
    return Message(detail="Вы вышли из системы")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
