"""Pydantic-схемы запросов и ответов."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ContentQuality, PostStatus, Role, SourceKind


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Аутентификация -------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORMModel):
    id: int
    username: str
    full_name: str | None
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    full_name: str | None = Field(default=None, max_length=255)
    role: Role = Role.editor


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


# --- Источники ------------------------------------------------------------

class SourceOut(ORMModel):
    id: int
    name: str
    url: str
    kind: SourceKind
    is_active: bool
    signature_name: str | None
    signature_suffix: str
    fetch_interval_minutes: int
    last_fetched_at: datetime | None
    last_error: str | None
    created_at: datetime


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=5, max_length=1024)
    kind: SourceKind = SourceKind.rss
    signature_name: str | None = Field(default=None, max_length=255)
    signature_suffix: str = Field(default="website", max_length=64)
    fetch_interval_minutes: int = Field(default=60, ge=5, le=10080)
    is_active: bool = True


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=1024)
    kind: SourceKind | None = None
    signature_name: str | None = Field(default=None, max_length=255)
    signature_suffix: str | None = Field(default=None, max_length=64)
    fetch_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    is_active: bool | None = None


# --- Статьи и посты -------------------------------------------------------

class PostOut(ORMModel):
    id: int
    article_id: int
    hashtags: str
    title: str
    body: str
    signature: str
    status: PostStatus
    ai_model: str | None
    ai_error: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    rendered: str
    char_count: int
    is_within_limit: bool


class PostUpdate(BaseModel):
    hashtags: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=512)
    body: str | None = None
    signature: str | None = Field(default=None, max_length=255)


class ArticleOut(ORMModel):
    id: int
    source_id: int
    url: str
    title: str
    author: str | None
    published_at: datetime | None
    summary: str | None
    content_quality: ContentQuality
    image_url: str | None
    categories: list[str] | None
    fetched_at: datetime


class ArticleDetail(ArticleOut):
    content: str | None
    post: PostOut | None


class ArticleListItem(ArticleOut):
    source_name: str
    post_status: PostStatus | None
    post_char_count: int | None


# --- Журнал ---------------------------------------------------------------

class AuditOut(ORMModel):
    id: int
    user_id: int | None
    username: str | None
    action: str
    entity_type: str | None
    entity_id: int | None
    details: dict | None
    ip: str | None
    created_at: datetime


# --- Служебное ------------------------------------------------------------

class FetchResult(BaseModel):
    source: str
    entries: int
    added: int
    with_full_text: int


class Message(BaseModel):
    detail: str
