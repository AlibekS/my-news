"""FastAPI-бэкенд + фоновый воркер обновления ленты."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import collector, config, db, reader
from .topics import DEFAULT_TOPICS, catalog

log = logging.getLogger("mynews")


async def background_worker() -> None:
    interval = config.REFRESH_INTERVAL_HOURS * 3600
    while True:
        last = db.last_fetched_at()
        await asyncio.sleep(0 if not last else max(0.0, last + interval - time.time()))
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


app = FastAPI(title="Волна", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/topics")
def topics():
    return {"topics": catalog(), "defaults": DEFAULT_TOPICS}


@app.get("/api/news")
def news(
    topics: str = Query(",".join(DEFAULT_TOPICS), description="ai,games,hardware,c-123"),
    custom: str = Query("[]", description='JSON: [{"id":"c-123","keywords":"apple, iphone"}]'),
    lang: str | None = Query(None, description="ru — только русскоязычные"),
):
    try:
        custom_list = [c for c in json.loads(custom) if isinstance(c, dict)][:20]
    except ValueError:
        custom_list = []
    topic_ids = [t for t in topics.split(",") if t][:30]
    since = int(time.time() - config.WINDOW_HOURS * 3600)
    sections = collector.build_sections(db.pool(since), topic_ids, custom_list, lang)
    for s in sections:
        for item in s["items"]:
            item.pop("weight", None)
    return {
        "sections": sections,
        "updated_at": db.last_fetched_at(),
        "refreshing": collector.is_running(),
    }


@app.post("/api/refresh")
async def refresh():
    return await collector.refresh()


@app.get("/api/sources")
def sources():
    return collector.load_status()


@app.get("/api/article/{article_id}")
async def article(article_id: int):
    data = await reader.get_article(article_id)
    if data is None:
        raise HTTPException(404, "Новость не найдена")
    return data
