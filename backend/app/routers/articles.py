"""Статьи и переработанные из них посты."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.ai.client import AIError, refine, rewrite, translate_captions
from app.deps import CurrentUser, DbDep, write_audit
from app.models import (
    Article,
    ArticleImage,
    ArticleView,
    ContentQuality,
    Post,
    PostStatus,
    Source,
    TelegramChannel,
)
from app.parsers.fetch import FetchError
from app.parsers.imagecache import ensure_cached, local_path, media_type_for, save_upload
from app.telegram.client import TelegramError, render_html, send_post
from app.telegram.config import current as telegram_config
from app.schemas import (
    ArticleDetail,
    ArticleListItem,
    ImageOut,
    ImageUpdate,
    Message,
    PostOut,
    PostRefine,
    PostUpdate,
)

log = logging.getLogger(__name__)

# Больше этого от редактора не принимаем
MAX_UPLOAD_BYTES = 12 * 1024 * 1024

router = APIRouter(prefix="/api/articles", tags=["articles"])


# Сортировка идёт на сервере: список подгружается порциями, и сортировать
# на клиенте значило бы упорядочивать только загруженную часть.
SORT_COLUMNS = {
    "published": Article.published_at,
    "fetched": Article.fetched_at,
    "title": Article.title,
    "quality": Article.content_quality,
}


@router.get("", response_model=list[ArticleListItem])
async def list_articles(
    db: DbDep,
    user: CurrentUser,
    source_id: int | None = None,
    status_filter: PostStatus | None = Query(default=None, alias="status"),
    only_unprocessed: bool = False,
    search: str | None = None,
    sort: str = Query(default="published"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    # Отметка «просмотрено» своя у каждого редактора, поэтому подтягиваем
    # её отдельным LEFT JOIN по текущему пользователю, а не полем статьи.
    seen = ArticleView.__table__.alias("seen")

    query = (
        select(Article, Source.name, seen.c.viewed_at)
        .join(Source, Source.id == Article.source_id)
        .outerjoin(
            seen,
            (seen.c.article_id == Article.id) & (seen.c.user_id == user.id),
        )
        .options(selectinload(Article.post), selectinload(Article.images))
    )

    if source_id is not None:
        query = query.where(Article.source_id == source_id)
    if search:
        query = query.where(Article.title.ilike(f"%{search}%"))
    if only_unprocessed:
        query = query.where(~Article.post.has())
    if status_filter is not None:
        query = query.where(Article.post.has(Post.status == status_filter))

    ascending = order == "asc"

    if sort == "source":
        column = Source.name
    elif sort in ("post", "chars"):
        # Эти поля живут в посте, которого у статьи может не быть
        query = query.outerjoin(Post, Post.article_id == Article.id)
        column = Post.status if sort == "post" else Post.updated_at
    else:
        column = SORT_COLUMNS.get(sort, Article.published_at)

    direction = column.asc() if ascending else column.desc()
    # nullslast независимо от направления: статьи без даты или без поста
    # всегда внизу, иначе они забивают первую страницу
    query = query.order_by(direction.nullslast(), Article.id.desc())

    rows = (await db.execute(query.limit(limit).offset(offset))).all()

    return [
        ArticleListItem(
            **{c.name: getattr(article, c.name) for c in Article.__table__.columns},
            source_name=source_name,
            post_status=article.post.status if article.post else None,
            post_char_count=article.post.char_count if article.post else None,
            image_count=len(article.images),
            is_viewed=viewed_at is not None,
            viewed_at=viewed_at,
        )
        for article, source_name, viewed_at in rows
    ]


@router.get("/{article_id}", response_model=ArticleDetail)
async def get_article(article_id: int, db: DbDep, user: CurrentUser):
    article = await db.scalar(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.post), selectinload(Article.images))
    )
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статья не найдена")

    # Открыл — значит просмотрел. ON CONFLICT, потому что открыть статью
    # в двух вкладках разом ничего ломать не должно.
    await db.execute(
        pg_insert(ArticleView)
        .values(article_id=article.id, user_id=user.id)
        .on_conflict_do_update(
            constraint="uq_article_view", set_={"viewed_at": func.now()}
        )
    )
    await db.commit()
    return article


@router.post("/{article_id}/rewrite", response_model=PostOut)
async def rewrite_article(article_id: int, request: Request, db: DbDep, user: CurrentUser):
    """Переработать статью в пост канала через ИИ."""
    article = await db.scalar(
        select(Article)
        .where(Article.id == article_id)
        .options(
            selectinload(Article.post),
            selectinload(Article.source),
            selectinload(Article.images),
        )
    )
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статья не найдена")

    if article.content_quality is ContentQuality.empty:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "У статьи нет текста — переработать нечего",
        )

    post = article.post
    if post is None:
        post = Post(article_id=article.id)
        db.add(post)

    if post.status is PostStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пост уже опубликован, повторная генерация запрещена")

    try:
        draft = await rewrite(article, article.source)
    except AIError as exc:
        post.status = PostStatus.failed
        post.ai_error = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    post.hashtags = draft.hashtags
    post.title = draft.title
    post.body = draft.body
    post.signature = draft.signature
    post.ai_raw_output = draft.raw
    post.ai_model = draft.model
    post.ai_error = None
    post.status = PostStatus.generated

    # Подписи к фотографиям переводим тем же проходом. Если перевод не
    # удался — пост всё равно сохраняем, подписи останутся на английском.
    pending = [image for image in article.images if image.caption and not image.caption_ru]
    if pending:
        try:
            for image, translated in zip(
                pending, await translate_captions([i.caption or "" for i in pending])
            ):
                image.caption_ru = translated
        except AIError as exc:
            log.warning("Подписи к фото не переведены: %s", exc)

    await write_audit(
        db,
        user=user,
        action="post.generate",
        entity_type="article",
        entity_id=article.id,
        details={
            "model": draft.model,
            "chars": draft.char_count,
            "captions": len(pending),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(post)
    return post


@router.post("/{article_id}/refine", response_model=PostOut)
async def refine_post(
    article_id: int, payload: PostRefine, request: Request, db: DbDep, user: CurrentUser
):
    """Правит готовый пост по указанию редактора."""
    article = await db.scalar(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.post), selectinload(Article.source))
    )
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статья не найдена")

    post = article.post
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пост ещё не создан")
    if post.status is PostStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Опубликованный пост править нельзя")

    # Отдаём модели то, что сейчас в посте, включая правки человека
    current = {
        "hashtags": post.hashtags.split(),
        "title": post.title,
        "body": post.body,
    }

    try:
        draft = await refine(article, article.source, current, payload.instruction)
    except AIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    post.hashtags = draft.hashtags
    post.title = draft.title
    post.body = draft.body
    post.ai_raw_output = draft.raw
    post.ai_model = draft.model
    post.ai_error = None
    post.status = PostStatus.edited
    post.edited_by_id = user.id

    await write_audit(
        db,
        user=user,
        action="post.refine",
        entity_type="article",
        entity_id=article_id,
        details={"instruction": payload.instruction[:200], "chars": post.char_count},
        request=request,
    )
    await db.commit()
    await db.refresh(post)
    return post


@router.patch("/{article_id}/post", response_model=PostOut)
async def update_post(
    article_id: int, payload: PostUpdate, request: Request, db: DbDep, user: CurrentUser
):
    post = await db.scalar(select(Post).where(Post.article_id == article_id))
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пост ещё не создан")
    if post.status is PostStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Опубликованный пост править нельзя")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(post, field, value)

    post.status = PostStatus.edited
    post.edited_by_id = user.id

    await write_audit(
        db,
        user=user,
        action="post.edit",
        entity_type="article",
        entity_id=article_id,
        details={"chars": post.char_count},
        request=request,
    )
    await db.commit()
    await db.refresh(post)
    return post


@router.post("/{article_id}/publish", response_model=PostOut)
async def publish_post(article_id: int, request: Request, db: DbDep, user: CurrentUser):
    post = await db.scalar(select(Post).where(Post.article_id == article_id))
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пост ещё не создан")
    if post.status is PostStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пост уже опубликован")

    # Лимит в 1000 символов — требование канала, поэтому это ошибка, а не предупреждение
    if not post.is_within_limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В посте {post.char_count} символов при лимите 1000 — сократите текст",
        )
    if not post.hashtags.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не проставлен хэштег")
    if not post.title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не заполнен заголовок")

    # Отправляем в канал, если публикация включена в настройках.
    # Пока выключена — кнопка просто помечает пост, как раньше.
    config = await telegram_config()
    sent = None

    if config.enabled:
        if not config.token:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Публикация в канал включена, но токен бота не задан",
            )

        images = list(
            await db.scalars(
                select(ArticleImage)
                .where(ArticleImage.article_id == article_id, ArticleImage.is_selected.is_(True))
                .order_by(ArticleImage.position)
            )
        )

        paths = []
        for image in images:
            try:
                if image.local_file:
                    path = local_path(image.local_file)
                elif image.url:
                    path, _ = await ensure_cached(image.url)
                else:
                    continue
                if path.exists():
                    paths.append(path)
            except FetchError as exc:
                log.warning("Фото %s не удалось подготовить: %s", image.id, exc)

        text = render_html(
            post.hashtags, post.title, post.body, post.signature, "Новости ИСККОН t.me/iskconru"
        )

        targets = list(
            await db.scalars(
                select(TelegramChannel).where(TelegramChannel.is_enabled.is_(True))
            )
        )
        if not targets:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Отправка включена, но ни один канал не выбран",
            )

        # Отправляем по очереди. Если упал первый — не публикуем никуда,
        # чтобы не оставить пост наполовину разосланным.
        results = []
        for index, target in enumerate(targets):
            try:
                results.append(await send_post(
                    token=config.token, channel=target.chat, text=text, photos=paths
                ))
            except TelegramError as exc:
                if index == 0:
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        f"Telegram не принял пост в {target.chat}: {exc}",
                    ) from exc
                # Первый канал уже принял — остальные ошибки только логируем
                log.error("Пост не ушёл в %s: %s", target.chat, exc)

        sent = results[0] if results else None

    post.status = PostStatus.published
    post.published_at = datetime.now(timezone.utc)
    if sent:
        post.telegram_message_id = sent.message_id
        post.telegram_url = sent.url

    await write_audit(
        db,
        user=user,
        action="post.publish",
        entity_type="article",
        entity_id=article_id,
        details={
            "chars": post.char_count,
            "hashtags": post.hashtags,
            **({"telegram": sent.url} if sent else {"telegram": "не отправлялось"}),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(post)
    return post


@router.post("/{article_id}/unpublish", response_model=PostOut)
async def unpublish_post(article_id: int, request: Request, db: DbDep, user: CurrentUser):
    post = await db.scalar(select(Post).where(Post.article_id == article_id))
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пост ещё не создан")

    post.status = PostStatus.edited
    post.published_at = None

    await write_audit(
        db,
        user=user,
        action="post.unpublish",
        entity_type="article",
        entity_id=article_id,
        request=request,
    )
    await db.commit()
    await db.refresh(post)
    return post


@router.get("/{article_id}/images/{image_id}/raw")
async def get_image_file(article_id: int, image_id: int, db: DbDep, user: CurrentUser):
    """Отдаёт саму картинку.

    Напрямую к источнику браузер обратиться не может: iskconnews.org закрыт
    Cloudflare и отдаёт 403 в том числе на файлы изображений. Поэтому качаем
    их сами и раздаём из локального кэша.
    """
    image = await db.scalar(
        select(ArticleImage).where(
            ArticleImage.id == image_id, ArticleImage.article_id == article_id
        )
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Картинка не найдена")

    # Загруженные редактором лежат у нас сразу, остальные докачиваем по адресу
    if image.local_file:
        path = local_path(image.local_file)
        if not path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл картинки потерян")
        media_type = media_type_for(image.local_file)
    elif image.url:
        try:
            path, media_type = await ensure_cached(image.url)
        except FetchError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Источник не отдал файл: {exc}"
            ) from exc
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У картинки нет ни файла, ни адреса")

    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/{article_id}/images", response_model=list[ImageOut], status_code=status.HTTP_201_CREATED)
async def upload_images(
    article_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUser,
    files: list[UploadFile] = File(...),
):
    """Добавляет к статье собственные фотографии редактора."""
    article = await db.scalar(
        select(Article).where(Article.id == article_id).options(selectinload(Article.images))
    )
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статья не найдена")

    next_position = max((image.position for image in article.images), default=-1) + 1
    added: list[ArticleImage] = []

    for upload in files:
        content = await upload.read()

        if not content:
            continue
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"«{upload.filename}» больше {MAX_UPLOAD_BYTES // 1024 // 1024} МБ",
            )

        try:
            name, _ = save_upload(content, upload.filename or "photo.jpg", upload.content_type or "")
        except ValueError as exc:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

        image = ArticleImage(
            article_id=article.id,
            local_file=name,
            caption=None,
            position=next_position,
            is_selected=True,  # раз редактор загрузил сам — значит она нужна
            is_uploaded=True,
            uploaded_by_id=user.id,
        )
        db.add(image)
        added.append(image)
        next_position += 1

    if not added:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файлы не переданы")

    await db.flush()
    await write_audit(
        db,
        user=user,
        action="image.upload",
        entity_type="article",
        entity_id=article_id,
        details={"файлов": len(added)},
        request=request,
    )
    await db.commit()
    for image in added:
        await db.refresh(image)
    return added


@router.delete("/{article_id}/images/{image_id}", response_model=Message)
async def delete_image(
    article_id: int, image_id: int, request: Request, db: DbDep, user: CurrentUser
):
    image = await db.scalar(
        select(ArticleImage).where(
            ArticleImage.id == image_id, ArticleImage.article_id == article_id
        )
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Картинка не найдена")

    # Файл в кэше не трогаем: он может быть общим для нескольких записей,
    # а места занимает немного.
    await db.delete(image)
    await write_audit(
        db,
        user=user,
        action="image.delete",
        entity_type="article",
        entity_id=article_id,
        details={"image_id": image_id, "загружена": image.is_uploaded},
        request=request,
    )
    await db.commit()
    return Message(detail="Фотография убрана")


@router.patch("/{article_id}/images/{image_id}", response_model=ImageOut)
async def update_image(
    article_id: int,
    image_id: int,
    payload: ImageUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUser,
):
    """Отметить картинку для поста или поправить её подпись."""
    image = await db.scalar(
        select(ArticleImage).where(
            ArticleImage.id == image_id, ArticleImage.article_id == article_id
        )
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Картинка не найдена")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(image, field, value)

    await write_audit(
        db,
        user=user,
        action="image.update",
        entity_type="article",
        entity_id=article_id,
        details={"image_id": image_id, **{k: str(v) for k, v in changes.items()}},
        request=request,
    )
    await db.commit()
    await db.refresh(image)
    return image


@router.delete("/{article_id}", response_model=Message)
async def delete_article(article_id: int, request: Request, db: DbDep, user: CurrentUser):
    article = await db.get(Article, article_id)
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статья не найдена")

    await db.delete(article)
    await write_audit(
        db,
        user=user,
        action="article.delete",
        entity_type="article",
        entity_id=article_id,
        request=request,
    )
    await db.commit()
    return Message(detail="Статья удалена")
