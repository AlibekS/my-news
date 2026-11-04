"""FastAPI-бэкенд + фоновый воркер обновления ленты."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import collector, config, db, reader, search
from .topics import DEFAULT_TOPICS, MAX_TOPICS, REGIONS, catalog

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
    return {"topics": catalog(), "defaults": DEFAULT_TOPICS, "max": MAX_TOPICS, "regions": REGIONS}


@app.get("/api/news")
def news(
    topics: str = Query(",".join(DEFAULT_TOPICS), description="ai,games,hardware,c-123"),
    custom: str = Query("[]", description='JSON: [{"id":"c-123","keywords":"apple, iphone"}]'),
    region: str = Query("ru", description="ru / en / kz"),
    hide: str = Query("[]", description='JSON: скрытые источники, ["DTF", "iXBT"]'),
):
    try:
        hidden = {str(h) for h in json.loads(hide) if isinstance(h, str)}
    except (ValueError, TypeError):
        hidden = set()
    try:
        custom_list = [c for c in json.loads(custom) if isinstance(c, dict)][:20]
    except ValueError:
        custom_list = []
    topic_ids = [t for t in topics.split(",") if t][:30]
    since = int(time.time() - config.WINDOW_HOURS * 3600)
    sections = collector.build_sections(db.pool(since), topic_ids, custom_list, region, hidden_sources=hidden)
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


_weather: dict = {"data": None, "ts": 0.0}


@app.get("/api/weather")
async def weather():
    """Текущая погода для виджета (кэш 15 минут)."""
    if _weather["data"] and time.time() - _weather["ts"] < 15 * 60:
        return _weather["data"]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={config.WEATHER_LAT}&longitude={config.WEATHER_LON}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m,is_day"
        "&daily=temperature_2m_max,temperature_2m_min&forecast_days=1&wind_speed_unit=ms"
        f"&timezone={config.WEATHER_TZ}"
    )
    try:
        async with collector.make_client() as client:
            r = await client.get(url, timeout=10)
            r.raise_for_status()
            j = r.json()
        cur, daily = j["current"], j.get("daily", {})
        data = {
            "ok": True, "city": config.WEATHER_CITY,
            "temp": cur["temperature_2m"], "feels": cur["apparent_temperature"],
            "code": cur["weather_code"], "is_day": bool(cur["is_day"]),
            "wind": cur["wind_speed_10m"], "humidity": cur["relative_humidity_2m"],
            "tmax": (daily.get("temperature_2m_max") or [None])[0],
            "tmin": (daily.get("temperature_2m_min") or [None])[0],
            "utc_offset": j.get("utc_offset_seconds", 5 * 3600),
        }
        _weather.update(data=data, ts=time.time())
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("Погода недоступна: %s", e)
        return _weather["data"] or {"ok": False, "city": config.WEATHER_CITY, "utc_offset": 5 * 3600}


@app.get("/api/search")
async def web_search(q: str = Query(..., min_length=1, max_length=200)):
    """Поиск: совпадения в ленте + результаты из интернета (на русском)."""
    data = await search.search(q)
    for p in data["local"]:
        p.pop("weight", None)
    return data


@app.get("/api/read")
async def read(url: str = Query(..., min_length=8, max_length=2000)):
    """Открыть любую статью из интернета в режиме чтения."""
    try:
        return await search.read_url(url)
    except search.BadURL as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:  # noqa: BLE001
        log.info("Не удалось прочитать %s: %s", url, e)
        raise HTTPException(502, "Не удалось загрузить страницу") from None


@app.get("/api/article/{article_id}")
async def article(article_id: int):
    data = await reader.get_article(article_id)
    if data is None:
        raise HTTPException(404, "Новость не найдена")
    return data
