from __future__ import annotations

import enum
import re
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------

class Role(str, enum.Enum):
    superadmin = "superadmin"  # заводит пользователей, правит источники и настройки ИИ
    editor = "editor"          # работает с новостями


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), default=Role.editor)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Кто завёл этого пользователя (у первого суперадмина — пусто)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[User | None] = relationship(remote_side=[id])

    @property
    def is_superadmin(self) -> bool:
        return self.role is Role.superadmin


# --------------------------------------------------------------------------
# Источники новостей
# --------------------------------------------------------------------------

_TITLE_NOISE = re.compile(r"[^0-9a-zа-яё]+")


def title_key_for(title: str) -> str:
    """Ключ для сравнения заголовков.

    Убираем регистр, знаки и пробелы: «ISKCON 60th Anniversary — Where It
    All Began» и «ISKCON 60th anniversary: where it all began» должны дать
    одну строку, иначе один сюжет с двух сайтов не сойдётся.
    """
    return _TITLE_NOISE.sub("", (title or "").casefold())[:512]


class SourceKind(str, enum.Enum):
    rss = "rss"          # RSS/Atom-фид
    archive = "archive"  # помесячный архив сайта: список «ARCHIVES» на главной
    html = "html"        # страница со списком ссылок
    newsletter = "newsletter"  # архив рассылок: выпуск — подборка ссылок на чужие сайты


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1024), unique=True)
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind, name="source_kind"), default=SourceKind.rss)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Как источник подписывается в готовом посте:
    #   «ISKCON News» website  ->  signature_name='ISKCON News', signature_suffix='website'
    signature_name: Mapped[str | None] = mapped_column(String(255))
    signature_suffix: Mapped[str] = mapped_column(String(64), default="website")

    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Свой шаблон промпта. Пусто — берётся шаблон по умолчанию.
    prompt_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL")
    )
    prompt_template: Mapped[PromptTemplate | None] = relationship(back_populates="sources")

    articles: Mapped[list[Article]] = relationship(back_populates="source", cascade="all, delete-orphan")

    @property
    def signature_line(self) -> str:
        name = self.signature_name or self.name
        return f"«{name}» {self.signature_suffix}"


# --------------------------------------------------------------------------
# Исходные статьи
# --------------------------------------------------------------------------

class ContentQuality(str, enum.Enum):
    full = "full"        # удалось скачать полный текст страницы
    excerpt = "excerpt"  # только анонс из RSS — для пересказа маловато
    empty = "empty"      # текста нет вовсе


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    source: Mapped[Source] = relationship(back_populates="articles")

    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1024))

    # Заголовок без регистра, знаков и лишних пробелов. По нему ловим
    # один и тот же сюжет, опубликованный на разных сайтах под своими
    # адресами: по URL такие пары не сходятся.
    title_key: Mapped[str | None] = mapped_column(String(512), index=True)

    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    summary: Mapped[str | None] = mapped_column(Text)   # анонс из фида
    content: Mapped[str | None] = mapped_column(Text)   # полный текст статьи
    content_quality: Mapped[ContentQuality] = mapped_column(
        Enum(ContentQuality, name="content_quality"), default=ContentQuality.empty
    )
    image_url: Mapped[str | None] = mapped_column(String(1024))
    categories: Mapped[list[str] | None] = mapped_column(JSONB)

    # Переиздание старого материала: сайт выложил его сегодня, но сама
    # запись двух-трёхлетней давности. В ленте по умолчанию прячем.
    is_archive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Дата, указанная в самом материале, если она там есть
    content_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    post: Mapped[Post | None] = relationship(
        back_populates="article", cascade="all, delete-orphan", uselist=False
    )
    images: Mapped[list[ArticleImage]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="ArticleImage.position",
    )
    videos: Mapped[list[ArticleVideo]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="ArticleVideo.position",
    )

    @property
    def text_for_ai(self) -> str:
        """Текст, который уходит в модель: полный, а если его нет — анонс."""
        return self.content or self.summary or ""


class ArticleVideo(Base):
    """Видеоролик из новости.

    У dandavats заметная часть публикаций — записи лекций: на странице один
    плеер и почти нет текста. Ссылку редактору нужно видеть, а обложку ролика
    забираем в галерею — иначе такой пост уходит вовсе без иллюстрации.
    """

    __tablename__ = "article_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    article: Mapped[Article] = relationship(back_populates="videos")

    url: Mapped[str] = mapped_column(String(1024))
    provider: Mapped[str] = mapped_column(String(32))       # youtube, vimeo, rutube, vk, file
    video_id: Mapped[str | None] = mapped_column(String(64))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    position: Mapped[int] = mapped_column(Integer, default=0)


class ArticleMention(Base):
    """Где ещё встретилась эта новость.

    Дайджест ISKCON Connection ссылается прямо на dandavats и iskconnews,
    поэтому одна и та же новость приходит из нескольких источников. Статью
    держим одну — ключ по каноническому адресу, — а источники копим здесь.
    """

    __tablename__ = "article_mentions"
    __table_args__ = (UniqueConstraint("article_id", "source_id", name="uq_article_mention"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    source: Mapped[Source] = relationship()

    # Адрес, по которому источник на неё сослался: у дайджеста он свой
    url: Mapped[str | None] = mapped_column(String(1024))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArticleView(Base):
    """Кто из редакторов открывал новость.

    Нужно, чтобы в ленте отличать непросмотренное. Запись per-user, а не
    одна на статью: у каждого редактора свой «прочитано».
    """

    __tablename__ = "article_views"
    __table_args__ = (UniqueConstraint("article_id", "user_id", name="uq_article_view"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user: Mapped[User] = relationship()

    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ArticleImage(Base):
    """Картинка из новости.

    Подпись берём из figcaption, alt или имени файла — на iskconnews.org
    её зашивают именно туда. Перевод подписи делает тот же модуль ИИ,
    что и текст поста.
    """

    __tablename__ = "article_images"
    __table_args__ = (UniqueConstraint("article_id", "url", name="uq_article_images_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    article: Mapped[Article] = relationship(back_populates="images")

    # У картинки из новости есть адрес на сайте источника; у загруженной
    # редактором — нет, вместо него имя файла в local_file.
    url: Mapped[str | None] = mapped_column(String(1024))
    local_file: Mapped[str | None] = mapped_column(String(255))

    caption: Mapped[str | None] = mapped_column(Text)      # как в оригинале
    caption_ru: Mapped[str | None] = mapped_column(Text)   # перевод
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    position: Mapped[int] = mapped_column(Integer, default=0)
    # Пойдёт ли картинка в пост. Первую выбираем автоматически.
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    # Загружена редактором вручную, а не взята из новости
    is_uploaded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Главная картинка поста: уходит в альбом первой, и именно её видно
    # в ленте канала под свёрнутым постом. На статью такая ровно одна.
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False)

    # Обложка ролика, а не кадр из статьи — помечаем, чтобы редактор
    # понимал, откуда картинка взялась
    from_video: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


# --------------------------------------------------------------------------
# Переработанные посты
# --------------------------------------------------------------------------

class PostStatus(str, enum.Enum):
    draft = "draft"          # создан, ИИ ещё не отработал
    generating = "generating"
    generated = "generated"  # ИИ отработал, ждёт редактора
    edited = "edited"        # правил человек
    published = "published"
    failed = "failed"


MAX_POST_CHARS = 1000


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("article_id", name="uq_posts_article_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    article: Mapped[Article] = relationship(back_populates="post")

    # Составные части поста — редактируются по отдельности
    hashtags: Mapped[str] = mapped_column(String(255), default="")   # "#ятры #фестивали"
    title: Mapped[str] = mapped_column(String(512), default="")      # выводится жирным
    body: Mapped[str] = mapped_column(Text, default="")
    signature: Mapped[str] = mapped_column(String(255), default="")  # «ISKCON News» website

    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status"), default=PostStatus.draft, index=True
    )

    # Что вернул ИИ до правок человека — чтобы всегда видеть разницу
    ai_raw_output: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(128))
    ai_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Куда ушёл пост в канале: id сообщения и прямая ссылка
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    telegram_url: Mapped[str | None] = mapped_column(String(255))

    edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    edited_by: Mapped[User | None] = relationship(foreign_keys=[edited_by_id])

    @property
    def rendered(self) -> str:
        """Пост целиком, как он уйдёт в канал.

        Формат снят с живых постов t.me/iskconru: хэштеги и жирный заголовок
        на одной строке, затем тело, затем двухстрочная подпись.
        """
        head = f"{self.hashtags} **{self.title}**".strip()
        tail = f"{self.signature}\nНовости ИСККОН t.me/iskconru".strip()
        return f"{head}\n\n{self.body.strip()}\n\n{tail}"

    @property
    def char_count(self) -> int:
        return len(self.rendered)

    @property
    def is_within_limit(self) -> bool:
        return self.char_count <= MAX_POST_CHARS


# --------------------------------------------------------------------------
# Шаблоны промптов
# --------------------------------------------------------------------------

class PromptTemplate(Base):
    """Инструкция для модели, по которой новость превращается в пост.

    Шаблон редактируется через интерфейс и назначается источнику: у разных
    сайтов бывает разный характер материалов. Блок с форматом ответа в шаблон
    не входит — его дописывает сервер, иначе неудачная правка сломала бы
    разбор JSON и генерация встала бы целиком.
    """

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)

    # Применяется к источникам, которым свой шаблон не назначен
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[User | None] = relationship()

    sources: Mapped[list[Source]] = relationship(back_populates="prompt_template")


# --------------------------------------------------------------------------
# Настройки публикации в Telegram
# --------------------------------------------------------------------------

class TelegramSettings(Base):
    """Одна строка на всё приложение.

    Публикуем через Bot API: это штатный способ. Альтернатива — клиент
    MTProto от имени живого аккаунта — потребовала бы хранить на сервере
    сессию личного аккаунта, а это полный доступ к переписке.
    """

    __tablename__ = "telegram_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    bot_token: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(128), default="@iskconru")
    # Пока выключено, кнопка «Опубликовать» только помечает пост в базе
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[User | None] = relationship()

    channels: Mapped[list[TelegramChannel]] = relationship(
        back_populates="settings", cascade="all, delete-orphan", order_by="TelegramChannel.id"
    )

    @property
    def token_hint(self) -> str | None:
        """Хвост токена для интерфейса — сам токен наружу не отдаём."""
        if not self.bot_token:
            return None
        return f"…{self.bot_token[-4:]}" if len(self.bot_token) > 8 else "…"


class TelegramChannel(Base):
    """Канал, куда бот публикует посты.

    Список ведём вручную: Bot API не позволяет узнать, в каких каналах
    состоит бот, — метода для этого попросту нет. Проверить можно только
    конкретный канал, который мы назвали.
    """

    __tablename__ = "telegram_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    settings_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_settings.id", ondelete="CASCADE"), index=True
    )
    settings: Mapped[TelegramSettings] = relationship(back_populates="channels")

    # К какой площадке относится канал. Заполняется миграцией у всех
    # существующих: до появления MAX площадка была ровно одна.
    platform_id: Mapped[int | None] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[Platform | None] = relationship(back_populates="channels")

    chat: Mapped[str] = mapped_column(String(128), unique=True)   # @имя или числовой id
    title: Mapped[str | None] = mapped_column(String(255))        # подтягивается при проверке
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(512))
    can_post: Mapped[bool | None] = mapped_column(Boolean)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------
# Настройки подключения к языковой модели
# --------------------------------------------------------------------------

class LlmSettings(Base):
    """Одна строка на всё приложение.

    Значения из .env остаются запасным вариантом: пока в базе ничего нет,
    работаем по ним, и приложение поднимается без предварительной настройки.
    """

    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    base_url: Mapped[str] = mapped_column(String(512), default="https://api.openai.com/v1")
    api_key: Mapped[str | None] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(128), default="gpt-4o")
    temperature: Mapped[float] = mapped_column(Float, default=0.4)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[User | None] = relationship()

    @property
    def key_hint(self) -> str | None:
        """Хвост ключа для интерфейса — сам ключ наружу не отдаём."""
        if not self.api_key:
            return None
        return f"…{self.api_key[-4:]}" if len(self.api_key) > 8 else "…"


# --------------------------------------------------------------------------
# Журнал действий
# --------------------------------------------------------------------------

class PlatformKind(str, enum.Enum):
    telegram = "telegram"
    max = "max"          # мессенджер MAX, botapi похож на телеграмный


class Platform(Base):
    """Подключённая площадка: бот в мессенджере и его токен.

    Площадок может быть несколько и разных: у каждой свой токен, свои
    каналы и свой способ отправки. Раньше настройки были только под
    Telegram, отсюда и старое имя таблицы каналов.
    """

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[PlatformKind] = mapped_column(
        Enum(PlatformKind, name="platform_kind"), default=PlatformKind.telegram
    )
    title: Mapped[str] = mapped_column(String(255))

    # Токен наружу не отдаём никогда — только признак и последние символы
    token: Mapped[str | None] = mapped_column(String(255))

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    bot_username: Mapped[str | None] = mapped_column(String(128))
    bot_id: Mapped[str | None] = mapped_column(String(64))
    last_status: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[User | None] = relationship()

    channels: Mapped[list[TelegramChannel]] = relationship(
        back_populates="platform", cascade="all, delete-orphan"
    )

    @property
    def token_hint(self) -> str | None:
        return f"…{self.token[-4:]}" if self.token else None


class FetchSettings(Base):
    """Расписание обхода источников. Строка всегда одна."""

    __tablename__ = "fetch_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Как часто обходить источники. Минуты, а не «час/день» строкой:
    # так в интерфейсе можно и выбрать из списка, и задать своё число.
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)

    # Граница, старше которой новости не берём. Два способа задать: жёсткая
    # дата («ничего раньше 1 июля») и скользящее окно («не старше 30 дней»).
    # Заданы оба — действует более поздняя из двух границ.
    min_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_age_days: Mapped[int | None] = mapped_column(Integer)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(Text)

    # До какого момента подписчикам уже рассказали о новостях. Считаем
    # от него, а не от результата одного обхода: обход может оборваться
    # на середине — например, службу перезапустили при выкладке, —
    # и тогда добавленное осталось бы без сводки навсегда.
    last_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[User | None] = relationship()


class BotSubscriber(Base):
    """Кто подписан на оповещения бота.

    Telegram не даёт спросить «кто мне писал» иначе как через getUpdates,
    поэтому подписчик заводится в тот момент, когда сам напишет боту.
    """

    __tablename__ = "bot_subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    username: Mapped[str | None] = mapped_column(String(128))
    full_name: Mapped[str | None] = mapped_column(String(255))

    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Смещение getUpdates хранится глобально, а не здесь; тут только человек
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # бот заблокирован у него


class BotState(Base):
    """Служебное состояние опроса Telegram. Строка всегда одна."""

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Смещение getUpdates: без него бот на каждом круге перечитывал бы
    # одни и те же сообщения и слал приветствие снова и снова
    update_offset: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    user: Mapped[User | None] = relationship()

    action: Mapped[str] = mapped_column(String(64), index=True)       # login, user.create, post.publish, ...
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# --------------------------------------------------------------------------
# Сессии
# --------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # случайный токен из куки
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user: Mapped[User] = relationship()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[str | None] = mapped_column(String(64))
