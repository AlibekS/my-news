"""FastAPI-бэкенд + фоновый воркер обновления ленты."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import collector, config, db, reader

log = logging.getLogger("mynews")


async def background_worker() -> None:
    interval = config.REFRESH_INTERVAL_HOURS * 3600
    while True:
        last = db.last_fetched_at()
        wait = 0 if not last else max(0.0, last + interval - time.time())
        await asyncio.sleep(wait)
        try:
            stats = await collector.refresh()
            if not stats["ok"]:
                await asyncio.sleep(15 * 60)  # сеть недоступна — повторим позже
        except Exception:  # noqa: BLE001
            log.exception("Ошибка фонового обновления")
            await asyncio.sleep(15 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    task = asyncio.create_task(background_worker())
    yield
    task.cancel()


app = FastAPI(title="My News", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/news")
def news(categories: str | None = Query(None, description="games,hardware,ai")):
    cats = [c for c in (categories or "").split(",") if c in config.CATEGORIES] or None
    return {
        "items": db.list_news(cats),
        "updated_at": db.last_fetched_at(),
        "refreshing": collector.is_running(),
        "categories": config.CATEGORIES,
    }


@app.post("/api/refresh")
async def refresh():
    return await collector.refresh()


@app.get("/api/article/{news_id}")
async def article(news_id: int):
    data = await reader.get_article(news_id)
    if data is None:
        raise HTTPException(404, "Новость не найдена")
    return data
