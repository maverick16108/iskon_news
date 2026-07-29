"""Настройки подключения к языковой модели. Доступны только суперадмину."""

import logging
import time

from fastapi import APIRouter, HTTPException, Request, status
from openai import APIError, AuthenticationError

from app.ai.client import AIError, build_client
from app.ai.config import LlmConfig, ensure_row
from app.deps import DbDep, SuperAdmin, write_audit
from app.schemas import LlmSettingsOut, LlmSettingsUpdate, LlmTestResult, ModelList

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/llm", tags=["settings"])


def _to_out(row) -> LlmSettingsOut:
    return LlmSettingsOut(
        base_url=row.base_url,
        model=row.model,
        temperature=row.temperature,
        api_key_set=bool(row.api_key),
        api_key_hint=row.key_hint,
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
        return LlmTestResult(ok=False, message=str(exc))
    except AuthenticationError:
        return LlmTestResult(ok=False, message="Ключ не принят: проверьте его и адрес API")
    except APIError as exc:
        return LlmTestResult(ok=False, message=f"Модель недоступна: {exc}")

    elapsed = int((time.perf_counter() - started) * 1000)
    answer = (response.choices[0].message.content or "").strip()

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
