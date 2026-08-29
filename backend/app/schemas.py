"""Pydantic-схемы запросов и ответов."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    DEFAULT_MIN_POST_CHARS,
    MAX_POST_CHARS,
    POST_CHARS_CEILING,
    POST_CHARS_FLOOR,
    ContentQuality,
    PlatformKind,
    PostStatus,
    Role,
    SourceKind,
)


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
    prompt_template_id: int | None
    prompt_template_name: str | None = None


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=5, max_length=1024)
    kind: SourceKind = SourceKind.rss
    signature_name: str | None = Field(default=None, max_length=255)
    signature_suffix: str = Field(default="website", max_length=64)
    fetch_interval_minutes: int = Field(default=60, ge=5, le=10080)
    is_active: bool = True
    prompt_template_id: int | None = None


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=1024)
    kind: SourceKind | None = None
    signature_name: str | None = Field(default=None, max_length=255)
    signature_suffix: str | None = Field(default=None, max_length=64)
    fetch_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    is_active: bool | None = None
    prompt_template_id: int | None = None


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
    source_date: datetime | None = None
    rendered: str
    char_count: int
    telegram_url: str | None = None


class PostUpdate(BaseModel):
    hashtags: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=512)
    body: str | None = None
    signature: str | None = Field(default=None, max_length=255)


class PostRefine(BaseModel):
    """Свободное указание модели: что поправить в готовом посте."""

    instruction: str = Field(min_length=3, max_length=1000)


class ImageOut(ORMModel):
    id: int
    url: str | None
    is_uploaded: bool
    caption: str | None
    caption_ru: str | None
    width: int | None
    height: int | None
    position: int
    is_selected: bool
    is_cover: bool = False      # главная: уходит в альбом первой
    from_video: bool = False    # это обложка ролика, а не кадр статьи


class VideoOut(ORMModel):
    id: int
    url: str
    provider: str
    thumbnail_url: str | None


class ImageUpdate(BaseModel):
    is_selected: bool | None = None
    is_cover: bool | None = None
    caption_ru: str | None = Field(default=None, max_length=300)


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
    is_archive: bool = False       # переиздание старой записи
    content_date: datetime | None = None


class FeedUpdates(BaseModel):
    """Что появилось в ленте после указанного момента.

    Здесь же отдаём время последнего обхода: лента показывает его в шапке,
    и отдельный запрос ради одной даты был бы лишним.
    """

    count: int
    latest: datetime | None
    last_run_at: datetime | None = None
    last_result: str | None = None


class RepeatEntry(BaseModel):
    """Где ещё встречается этот же сюжет."""

    source: str
    url: str | None = None
    article_id: int | None = None   # если у повтора своя карточка в ленте
    # Состояние поста у двойника: публиковали этот сюжет или ещё нет
    post_status: PostStatus | None = None
    telegram_url: str | None = None


class PostLimits(BaseModel):
    """Границы длины поста для этой статьи: из шаблона, назначенного её
    источнику. По ним считается счётчик в редакторе."""

    min_chars: int
    max_chars: int


class ArticleDetail(ArticleOut):
    content: str | None
    post: PostOut | None
    images: list[ImageOut]
    videos: list[VideoOut] = []
    repeats: list[RepeatEntry] = []   # тот же сюжет в других источниках
    # Границы длины из шаблона, назначенного источнику этой статьи
    post_limits: PostLimits = PostLimits(
        min_chars=DEFAULT_MIN_POST_CHARS, max_chars=MAX_POST_CHARS
    )


class ArticleListItem(ArticleOut):
    source_name: str
    post_status: PostStatus | None
    post_char_count: int | None
    # Верхняя граница из шаблона источника: по ней в ленте краснеет счётчик
    post_max_chars: int = MAX_POST_CHARS
    image_count: int
    video_count: int = 0
    is_viewed: bool = False          # открывал ли новость кто-нибудь из редакторов
    viewed_at: datetime | None = None
    viewed_by: str | None = None     # кто открыл первым
    # Все источники, принёсшие этот сюжет: сам источник статьи, все, кто
    # на неё сослался, и источники статей с таким же заголовком
    repeat_sources: list[str] = []
    repeat_article_ids: list[int] = []   # статьи-двойники под другими адресами
    # Этот же сюжет уже публиковали в другой карточке
    repeat_published: bool = False


# --- Шаблоны промптов -------------------------------------------------------

class PromptOut(BaseModel):
    id: int
    name: str
    description: str | None
    body: str
    is_default: bool
    post_min_chars: int
    post_max_chars: int
    created_at: datetime
    updated_at: datetime
    updated_by: str | None
    used_by_sources: int


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    body: str = Field(min_length=20)
    is_default: bool = False
    post_min_chars: int = Field(
        default=DEFAULT_MIN_POST_CHARS, ge=POST_CHARS_FLOOR, le=POST_CHARS_CEILING
    )
    post_max_chars: int = Field(
        default=MAX_POST_CHARS, ge=POST_CHARS_FLOOR, le=POST_CHARS_CEILING
    )


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    body: str | None = Field(default=None, min_length=20)
    is_default: bool | None = None
    post_min_chars: int | None = Field(
        default=None, ge=POST_CHARS_FLOOR, le=POST_CHARS_CEILING
    )
    post_max_chars: int | None = Field(
        default=None, ge=POST_CHARS_FLOOR, le=POST_CHARS_CEILING
    )


class PlaceholderInfo(BaseModel):
    token: str
    description: str


# --- Настройки языковой модели --------------------------------------------

class LlmSettingsOut(BaseModel):
    base_url: str
    model: str
    temperature: float
    # Сам ключ наружу не отдаём никогда — только признак и последние символы
    api_key_set: bool
    api_key_hint: str | None
    # Чем закончилось последнее обращение к модели
    last_ok_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    out_of_money: bool = False
    updated_at: datetime
    updated_by: str | None


class LlmSettingsUpdate(BaseModel):
    base_url: str | None = Field(default=None, min_length=5, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)


class PostResize(BaseModel):
    """Новая длина поста: редактор нажал «короче» или «длиннее»."""

    target: int = Field(ge=POST_CHARS_FLOOR, le=POST_CHARS_CEILING)


class LlmTestResult(BaseModel):
    ok: bool
    message: str
    model: str | None = None
    elapsed_ms: int | None = None


class ModelList(BaseModel):
    models: list[str]


# --- Публикация в Telegram --------------------------------------------------

class TelegramSettingsOut(BaseModel):
    channel: str
    is_enabled: bool
    # Сам токен наружу не отдаём — только признак и последние символы
    token_set: bool
    token_hint: str | None
    updated_at: datetime
    updated_by: str | None


class TelegramSettingsUpdate(BaseModel):
    bot_token: str | None = Field(default=None, max_length=255)
    channel: str | None = Field(default=None, min_length=2, max_length=128)
    is_enabled: bool | None = None


class TelegramChannelOut(BaseModel):
    id: int
    chat: str
    title: str | None
    is_enabled: bool
    can_post: bool | None
    last_status: str | None
    last_checked_at: datetime | None


class TelegramChannelCreate(BaseModel):
    chat: str = Field(min_length=2, max_length=128)


class TelegramChannelUpdate(BaseModel):
    is_enabled: bool | None = None


class TelegramState(BaseModel):
    """Что произойдёт при нажатии «Опубликовать»."""

    is_enabled: bool
    ready: list[str] = []      # каналы, готовые принять пост
    blocked: list[str] = []    # отмечены, но бот там публиковать не может


class TelegramInfo(BaseModel):
    token_set: bool
    is_enabled: bool
    bot_username: str | None = None
    bot_name: str | None = None
    bot_id: int | None = None
    channels: list[TelegramChannelOut] = []
    message: str = ""
    # Пока стоит вебхук, бот не принимает команды от людей
    webhook_url: str | None = None


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
    images: int = 0


class Message(BaseModel):
    detail: str


# --- Расписание обхода и подписчики бота ------------------------------------

class FetchSettingsOut(BaseModel):
    is_enabled: bool
    interval_minutes: int
    # Граница возраста: новости старше не собираем
    min_published_at: datetime | None
    max_age_days: int | None
    last_run_at: datetime | None
    last_result: str | None
    last_reported_at: datetime | None = None
    updated_at: datetime
    updated_by: str | None


class FetchSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    min_published_at: datetime | None = None
    # Ноль и пусто означают «без ограничения по возрасту»
    max_age_days: int | None = Field(default=None, ge=0, le=3650)
    # От пяти минут до недели: чаще — невежливо к сайтам, реже — смысла нет
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)


class BotSubscriberOut(BaseModel):
    id: int
    chat_id: str
    username: str | None
    full_name: str | None
    notify: bool
    is_blocked: bool
    created_at: datetime
    last_notified_at: datetime | None


# --- Площадки публикации ----------------------------------------------------

class ChannelOut(BaseModel):
    id: int
    platform_id: int | None
    chat: str
    title: str | None
    is_enabled: bool
    can_post: bool | None
    last_status: str | None
    last_checked_at: datetime | None


class ChannelCreate(BaseModel):
    chat: str = Field(min_length=2, max_length=128)


class ChannelUpdate(BaseModel):
    is_enabled: bool | None = None


class PlatformOut(BaseModel):
    id: int
    kind: PlatformKind
    title: str
    is_enabled: bool
    # Сам токен наружу не отдаём — только признак и последние символы
    token_set: bool
    token_hint: str | None
    bot_username: str | None
    bot_id: str | None
    last_status: str | None
    last_checked_at: datetime | None
    channels: list[ChannelOut] = []


class PlatformCreate(BaseModel):
    kind: PlatformKind
    title: str = Field(min_length=1, max_length=255)
    token: str = Field(default="", max_length=255)


class PlatformUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    token: str | None = Field(default=None, max_length=255)
    is_enabled: bool | None = None
