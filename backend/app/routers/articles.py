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
    ArticleMention,
    ArticleVideo,
    ArticleView,
    ContentQuality,
    Platform,
    PlatformKind,
    Post,
    PostStatus,
    Source,
    TelegramChannel,
)
from app.parsers.fetch import FetchError, extract_text, fetch_html
from app.parsers.images import extract_images
from app.parsers.ingest import MIN_FULL_TEXT_CHARS
from app.parsers.videos import extract_videos
from app.parsers.imagecache import ensure_cached, local_path, media_type_for, save_upload
from app.publishers import max as max_api
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
    RepeatEntry,
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


async def collect_repeats(
    db: DbDep, articles: list[Article]
) -> dict[int, list[RepeatEntry]]:
    """Где ещё встречается каждый из сюжетов.

    Совпадения бывают двух видов. Точные: дайджест ISKCON Connection даёт
    ссылку на тот же адрес dandavats, и это одна статья с несколькими
    упоминаниями. Неточные: один сюжет вышел на двух сайтах под своими
    адресами — такие сводим по ключу заголовка.
    """
    if not articles:
        return {}

    ids = [a.id for a in articles]
    keys = {a.title_key for a in articles if a.title_key}

    # Кто принёс — включая источник самой статьи
    mentions = (
        await db.execute(
            select(ArticleMention.article_id, Source.name, ArticleMention.url)
            .join(Source, Source.id == ArticleMention.source_id)
            .where(ArticleMention.article_id.in_(ids))
        )
    ).all()

    by_article: dict[int, list[RepeatEntry]] = {a.id: [] for a in articles}
    for article_id, source_name, url in mentions:
        by_article[article_id].append(RepeatEntry(source=source_name, url=url))

    # Статьи-двойники под другими адресами
    twins: dict[str, list[tuple[int, str, str]]] = {}
    if keys:
        rows = (
            await db.execute(
                select(Article.id, Article.title_key, Source.name, Article.url)
                .join(Source, Source.id == Article.source_id)
                .where(Article.title_key.in_(keys))
            )
        ).all()
        for twin_id, key, source_name, url in rows:
            twins.setdefault(key, []).append((twin_id, source_name, url))

    for article in articles:
        for twin_id, source_name, url in twins.get(article.title_key or "", []):
            if twin_id == article.id:
                continue
            by_article[article.id].append(
                RepeatEntry(source=source_name, url=url, article_id=twin_id)
            )

    return by_article


@router.get("", response_model=list[ArticleListItem])
async def list_articles(
    db: DbDep,
    user: CurrentUser,
    source_id: int | None = None,
    status_filter: PostStatus | None = Query(default=None, alias="status"),
    only_unprocessed: bool = False,
    include_archive: bool = False,
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
        .options(
            selectinload(Article.post),
            selectinload(Article.images),
            selectinload(Article.videos),
        )
    )

    # Переиздания старых записей в ленте не нужны: сайт выложил их сегодня,
    # но материал давний. Показываем только по отдельной просьбе.
    if not include_archive:
        query = query.where(Article.is_archive.is_(False))

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
    repeats = await collect_repeats(db, [article for article, _, _ in rows])

    return [
        ArticleListItem(
            **{c.name: getattr(article, c.name) for c in Article.__table__.columns},
            source_name=source_name,
            post_status=article.post.status if article.post else None,
            post_char_count=article.post.char_count if article.post else None,
            image_count=len(article.images),
            video_count=len(article.videos),
            is_viewed=viewed_at is not None,
            viewed_at=viewed_at,
            # В ленте хватает списка названий: подробности — в самой новости
            repeat_sources=sorted(
                {e.source for e in repeats.get(article.id, [])} - {source_name}
            ),
            repeat_article_ids=sorted(
                {e.article_id for e in repeats.get(article.id, []) if e.article_id}
            ),
        )
        for article, source_name, viewed_at in rows
    ]


@router.get("/{article_id}", response_model=ArticleDetail)
async def get_article(article_id: int, db: DbDep, user: CurrentUser):
    article = await db.scalar(
        select(Article)
        .where(Article.id == article_id)
        .options(
            selectinload(Article.post),
            selectinload(Article.images),
            selectinload(Article.videos),
        )
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

    detail = ArticleDetail.model_validate(article)
    entries = (await collect_repeats(db, [article])).get(article.id, [])
    # Источник самой статьи в списке «где ещё» лишний
    own = await db.scalar(select(Source.name).where(Source.id == article.source_id))
    detail.repeats = [e for e in entries if e.source != own]
    return detail


@router.post("/{article_id}/refetch", response_model=ArticleDetail)
async def refetch_article(article_id: int, request: Request, db: DbDep, user: CurrentUser):
    """Заново читает страницу источника: текст, картинки, ролики.

    Нужно, когда сайт доложил материал после нашего обхода или когда
    статью забрали до того, как заработало извлечение роликов.
    """
    article = await db.scalar(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.images), selectinload(Article.videos))
    )
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Статья не найдена")

    try:
        html = await fetch_html(article.url)
    except FetchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Источник не ответил: {exc}") from exc

    content = extract_text(html)
    images = extract_images(html, article.url)
    videos = extract_videos(html, article.url)

    if content and len(content) >= MIN_FULL_TEXT_CHARS:
        article.content = content
        article.content_quality = ContentQuality.full
    elif not article.content:
        article.content_quality = (
            ContentQuality.excerpt if article.summary else ContentQuality.empty
        )

    # Ролики просто заменяем: своего в них редактор не правит
    article.videos = [
        ArticleVideo(
            url=video.url,
            provider=video.provider,
            video_id=video.video_id,
            thumbnail_url=video.thumbnail_url,
            position=index,
        )
        for index, video in enumerate(videos)
    ]

    # Обложки роликов идут в галерею вслед за картинками статьи
    fresh = [(i.url, i.caption, i.width, i.height, False) for i in images]
    fresh += [
        (v.thumbnail_url, None, None, None, True)
        for v in videos
        if v.thumbnail_url and v.thumbnail_url not in {i.url for i in images}
    ]

    # Загруженные редактором файлы и его отметки сохраняем: перечитывание
    # обновляет то, что пришло с сайта, а не отменяет ручную работу
    kept = {img.url for img in article.images if img.is_uploaded or img.url is None}
    existing = {img.url: img for img in article.images if img.url not in kept}

    for img in list(article.images):
        if img.url not in kept and img.url not in {url for url, *_ in fresh}:
            article.images.remove(img)

    position = max((img.position for img in article.images), default=-1)
    added = 0
    for url, caption, width, height, from_video in fresh:
        if url in existing or url in kept:
            continue
        position += 1
        added += 1
        article.images.append(
            ArticleImage(
                url=url,
                caption=caption,
                width=width,
                height=height,
                position=position,
                is_selected=not article.images,
                from_video=from_video,
            )
        )

    if not article.image_url and fresh:
        article.image_url = fresh[0][0]

    await write_audit(
        db,
        user=user,
        action="article.refetch",
        entity_type="article",
        entity_id=article.id,
        details={"картинок добавлено": added, "роликов": len(videos)},
        request=request,
    )
    await db.commit()

    return await get_article(article_id, db, user)


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

    # Рассылаем по всем включённым площадкам: Telegram, MAX и что ещё
    # добавят. Каждая со своим токеном и своим способом отправки.
    platforms = list(
        await db.scalars(
            select(Platform)
            .where(Platform.is_enabled.is_(True))
            .options(selectinload(Platform.channels))
        )
    )

    # Главная идёт первой: в ленте канала под свёрнутым постом видно
    # именно её, остальные — только когда пост раскроют
    images = list(
        await db.scalars(
            select(ArticleImage)
            .where(ArticleImage.article_id == article_id, ArticleImage.is_selected.is_(True))
            .order_by(ArticleImage.is_cover.desc(), ArticleImage.position)
        )
    )

    sent = None
    delivered: list[str] = []

    targets = [
        (platform, channel)
        for platform in platforms
        if platform.token
        for channel in platform.channels
        if channel.is_enabled
    ]

    if targets:
        paths = []
        image_urls = []
        for image in images:
            try:
                if image.local_file:
                    path = local_path(image.local_file)
                elif image.url:
                    path, _ = await ensure_cached(image.url)
                    image_urls.append(image.url)
                else:
                    continue
                if path.exists():
                    paths.append(path)
            except FetchError as exc:
                log.warning("Фото %s не удалось подготовить: %s", image.id, exc)

        channel_line = "Новости ИСККОН t.me/iskconru"

        # Если первая же отправка не удалась — не публикуем никуда, чтобы
        # пост не остался разосланным наполовину
        for index, (platform, channel) in enumerate(targets):
            try:
                if platform.kind is PlatformKind.telegram:
                    text = render_html(
                        post.hashtags, post.title, post.body, post.signature, channel_line
                    )
                    result = await send_post(
                        token=platform.token, channel=channel.chat, text=text, photos=paths
                    )
                    if sent is None:
                        sent = result
                else:
                    text = max_api.render_text(
                        post.hashtags, post.title, post.body, post.signature, channel_line
                    )
                    await max_api.send_post(platform.token, channel.chat, text, image_urls)

                delivered.append(f"{platform.title}: {channel.chat}")
            except (TelegramError, max_api.MaxError) as exc:
                if index == 0:
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        f"{platform.title} не принял пост в {channel.chat}: {exc}",
                    ) from exc
                log.error("Пост не ушёл в %s (%s): %s", channel.chat, platform.title, exc)

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
            "куда ушло": ", ".join(delivered) or "никуда: площадки выключены",
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

    if changes.get("is_cover"):
        # Главная на статью ровно одна: снимаем отметку с остальных
        others = await db.scalars(
            select(ArticleImage).where(
                ArticleImage.article_id == article_id, ArticleImage.id != image.id
            )
        )
        for other in others:
            other.is_cover = False
        # Главная всегда идёт в пост: отмечать её отдельно незачем
        image.is_selected = True

    # Сняли отметку с главной — снимаем и признак главной, иначе
    # в альбоме первой оказалась бы картинка, которой там нет
    if changes.get("is_selected") is False:
        image.is_cover = False

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
