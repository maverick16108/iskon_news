"""Пароли и сессионные токены."""

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

SESSION_COOKIE = "iskcon_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Битый хеш в базе — считаем, что пароль не подошёл, а не падаем
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry(ttl_seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)


def validate_password_strength(password: str) -> str | None:
    """Возвращает текст ошибки или None, если пароль годится."""
    if len(password) < 8:
        return "Пароль должен быть не короче 8 символов"
    if password.isdigit():
        return "Пароль не может состоять только из цифр"
    if password.lower() in {"password", "12345678", "qwerty123", "пароль123"}:
        return "Слишком простой пароль"
    return None
