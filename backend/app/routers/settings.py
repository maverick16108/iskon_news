"""Настройки подключения к языковой модели. Доступны только суперадмину."""

import logging
import time

from fastapi import APIRouter, HTTPException, Request, status
from openai import APIError, AuthenticationError, RateLimitError

from app.ai.client import AIError, build_client, is_quota_error
from app.ai.config import remember_outcome
from app.ai.config import LlmConfig, ensure_row
from app.deps import CurrentUser, DbDep, SuperAdmin, write_audit
from app.schemas import (
    LlmSettingsOut,
    LlmSettingsUpdate,
    LlmTestResult,
    ModelList,
    PostLimits,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/llm", tags=["settings"])


def _to_out(row) -> LlmSettingsOut:
    return LlmSettingsOut(
        base_url=row.base_url,
        model=row.model,
        temperature=row.temperature,
        post_min_chars=row.post_min_chars,
        post_max_chars=row.post_max_chars,
        api_key_set=bool(row.api_key),
        api_key_hint=row.key_hint,
        last_ok_at=row.last_ok_at,
        last_error=row.last_error,
        last_error_at=row.last_error_at,
        out_of_money=row.out_of_money,
        updated_at=row.updated_at,
        updated_by=row.updated_by.username if row.updated_by else None,
    )


@router.get("", response_model=LlmSettingsOut)
async def get_settings(db: DbDep, admin: SuperAdmin):
    row = await ensure_row(db)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.patch("", response_model=LlmSettingsOut)
async def update_settings(
    payload: LlmSettingsUpdate, request: Request, db: DbDep, admin: SuperAdmin
):
    row = await ensure_row(db)
    changes = payload.model_dump(exclude_unset=True)

    # Пустая строка в ключе означает «не менять», а не «стереть»:
    # интерфейс показывает только хвост, и присылать ключ каждый раз незачем.
    if not changes.get("api_key"):
        changes.pop("api_key", None)

    # Границы могут прийти по одной, поэтому сверяем со значением, которое
    # получится после правки, а не с присланным. Иначе «поднять минимум»
    # прошло бы мимо проверки и оставило диапазон вывернутым наизнанку.
    new_min = changes.get("post_min_chars", row.post_min_chars)
    new_max = changes.get("post_max_chars", row.post_max_chars)
    if new_min > new_max:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Нижняя граница длины ({new_min}) больше верхней ({new_max})",
        )

    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_by_id = admin.id

    await write_audit(
        db,
        user=admin,
        action="llm.update",
        entity_type="llm_settings",
        entity_id=row.id,
        # Ключ в журнал не пишем — только факт его смены
        details={
            **{k: str(v) for k, v in changes.items() if k != "api_key"},
            **({"api_key": "изменён"} if "api_key" in changes else {}),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.get("/post-limits", response_model=PostLimits)
async def get_post_limits(db: DbDep, user: CurrentUser):
    """Границы длины поста. Открыты любому вошедшему: по ним редактор
    видит счётчик символов и знает, когда публикация не пройдёт."""
    row = await ensure_row(db)
    await db.commit()
    await db.refresh(row)
    return PostLimits(min_chars=row.post_min_chars, max_chars=row.post_max_chars)


@router.post("/test", response_model=LlmTestResult)
async def test_connection(db: DbDep, admin: SuperAdmin):
    """Делает короткий запрос к модели и сообщает, отвечает ли она."""
    row = await ensure_row(db)
    await db.commit()

    config = LlmConfig(
        base_url=row.base_url,
        api_key=row.api_key or "",
        model=row.model,
        temperature=row.temperature,
    )

    started = time.perf_counter()
    try:
        response = await build_client(config).chat.completions.create(
            model=config.model,
            messages=[{"role": "user", "content": "Ответь одним словом: работает"}],
            max_tokens=10,
        )
    except AIError as exc:
        await remember_outcome(str(exc), out_of_money=is_quota_error(exc))
        return LlmTestResult(ok=False, message=str(exc))
    except AuthenticationError as exc:
        сообщение = "Ключ не принят: проверьте его и адрес API"
        await remember_outcome(сообщение)
        return LlmTestResult(ok=False, message=сообщение)
    except RateLimitError as exc:
        # Здесь же выясняется, что кончились деньги: у обоих случаев
        # один код ответа, различаются они только типом ошибки в теле
        if is_quota_error(exc):
            сообщение = (
                "На счёте OpenAI закончились средства — переработка "
                "не работает, пока баланс не пополнят"
            )
            await remember_outcome(сообщение, out_of_money=True)
            return LlmTestResult(ok=False, message=сообщение)
        сообщение = f"Превышен лимит запросов: {exc}"
        await remember_outcome(сообщение)
        return LlmTestResult(ok=False, message=сообщение)
    except APIError as exc:
        сообщение = f"Модель недоступна: {exc}"
        await remember_outcome(сообщение)
        return LlmTestResult(ok=False, message=сообщение)

    elapsed = int((time.perf_counter() - started) * 1000)
    answer = (response.choices[0].message.content or "").strip()
    await remember_outcome(None)

    return LlmTestResult(
        ok=True,
        message=f"Связь есть, ответ за {elapsed} мс: «{answer[:60]}»",
        model=response.model,
        elapsed_ms=elapsed,
    )


@router.get("/models", response_model=ModelList)
async def list_models(db: DbDep, admin: SuperAdmin):
    """Список моделей, доступных по текущему ключу."""
    row = await ensure_row(db)
    await db.commit()

    config = LlmConfig(
        base_url=row.base_url,
        api_key=row.api_key or "",
        model=row.model,
        temperature=row.temperature,
    )

    try:
        response = await build_client(config).models.list()
    except AIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except APIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось получить список: {exc}") from exc

    # Чат-модели наверх: в списке OpenAI полно эмбеддингов, tts и прочего
    names = sorted(model.id for model in response.data)
    chat_first = [n for n in names if n.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))]
    others = [n for n in names if n not in chat_first]

    return ModelList(models=chat_first + others)
