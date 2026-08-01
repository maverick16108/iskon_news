import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.hashtags import NEWS_HASHTAGS
from app.config import settings
from app.worker import bot_loop, fetch_loop
from app.routers import (
    articles,
    audit,
    auth,
    prompts,
    schedule,
    settings as settings_router,
    sources,
    telegram as telegram_router,
    users,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.openai_api_key:
        log.warning("OPENAI_API_KEY не задан — переработка новостей работать не будет")

    # Планировщик обхода и опрос бота живут в этом же процессе: отдельной
    # службы им не нужно, а от запуска в несколько процессов защищает
    # советующая блокировка внутри самих задач.
    tasks = [
        asyncio.create_task(fetch_loop(), name="fetch-loop"),
        asyncio.create_task(bot_loop(), name="bot-loop"),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="ИСККОН Новости",
    description="Сбор новостей из источников и переработка их в посты канала t.me/iskconru",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,  # обязательно: сессия ездит в httpOnly-куке
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(sources.router)
app.include_router(articles.router)
app.include_router(audit.router)
app.include_router(settings_router.router)
app.include_router(prompts.router)
app.include_router(telegram_router.router)
app.include_router(schedule.router)


@app.get("/api/health", tags=["service"])
async def health():
    return {"status": "ok"}


@app.get("/api/hashtags", tags=["service"], response_model=list[str])
async def hashtags():
    """Теги канала, которые разрешено ставить. Единый источник правды — бэкенд."""
    return list(NEWS_HASHTAGS)
