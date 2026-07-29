"""Статьи и переработанные из них посты."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.client import AIError, rewrite, translate_captions
from app.deps import CurrentUser, DbDep, write_audit
from app.models import Article, ArticleImage, ContentQuality, Post, PostStatus, Source
from app.parsers.fetch import FetchError
from app.parsers.imagecache import ensure_cached
from app.schemas import ArticleDetail, ArticleListItem, ImageOut, ImageUpdate, Message, PostOut, PostUpdate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("", response_model=list[ArticleListItem])
async def list_articles(
    db: DbDep,
    user: CurrentUser,
    source_id: int | None = None,
    status_filter: PostStatus | None = Query(default=None, alias="status"),
    only_unprocessed: bool = False,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    query = (
        select(Article, Source.name)
        .join(Source, Source.id == Article.source_id)
        .options(selectinload(Article.post), selectinload(Article.images))
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
    )

    if source_id is not None:
        query = query.where(Article.source_id == source_id)
    if search:
        query = query.where(Article.title.ilike(f"%{search}%"))
    if only_unprocessed:
        query = query.where(~Article.post.has())
    if status_filter is not None:
        query = query.where(Article.post.has(Post.status == status_filter))

    rows = (await db.execute(query.limit(limit).offset(offset))).all()

    return [
        ArticleListItem(
            **{c.name: getattr(article, c.name) for c in Article.__table__.columns},
            source_name=source_name,
            post_status=article.post.status if article.post else None,
            post_char_count=article.post.char_count if article.post else None,
            image_count=len(article.images),
        )
        for article, source_name in rows
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

    post.status = PostStatus.published
    post.published_at = datetime.now(timezone.utc)

    await write_audit(
        db,
        user=user,
        action="post.publish",
        entity_type="article",
        entity_id=article_id,
        details={"chars": post.char_count, "hashtags": post.hashtags},
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

    try:
        path, media_type = await ensure_cached(image.url)
    except FetchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Источник не отдал файл: {exc}") from exc

    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


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
