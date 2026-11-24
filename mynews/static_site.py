"""Статическая версия сайта для GitHub Pages (или любого статического хостинга).

Собирает ленту тем же конвейером, что и сервер, и раскладывает результат в папку
из обычных файлов:

    index.html                  интерфейс (с флагом статического режима)
    data/topics.json            каталог тем        (= /api/topics)
    data/news-{ru,en,kz}.json   пул новостей региона (темы раскладывает браузер)
    data/sources.json           статус лент        (= /api/sources)
    data/a/{id}.json            полный текст статей (= /api/article/{id})

Запуск: python tools/build_site.py  (см. .github/workflows/pages.yml).
Локальный режим (python run.py) от этого не меняется.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from . import collector, config, db, reader
from .topics import DEFAULT_TOPICS, MAX_TOPICS, REGIONS, TOPICS, catalog

log = logging.getLogger("mynews.static")

STATIC_FLAG = "<script>window.VOLNA_STATIC = true;</script>"
ITEM_FIELDS = (
    "id", "topics", "title", "summary", "image_url", "source_url", "discussion_url", "source",
    "lang", "region", "comments_count", "score", "weight", "also", "created_at",
)
SUMMARY_CHARS = 600          # в карточках и поиске больше не нужно
ARTICLES_PER_TOPIC = config.PER_TOPIC_LIMIT + 6   # запас на скрытые источники и свои темы
MAX_ARTICLES = int(config._env("STATIC_MAX_ARTICLES", "900"))


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def slim(item: dict) -> dict:
    out = {f: item.get(f) for f in ITEM_FIELDS}
    out["summary"] = (out["summary"] or "")[:SUMMARY_CHARS]
    return out


def region_pool(pool: list[dict], region: str) -> list[dict]:
    """То же, что фильтр региона в collector.build_sections."""
    out = [p for p in pool if p.get("region") == region]
    if region == "kz":  # казахстанские СМИ — только материалы на русском
        out = [p for p in out if p.get("lang") == "ru"]
    return out


def article_ids(pool: list[dict], per_topic: int = ARTICLES_PER_TOPIC, limit: int = MAX_ARTICLES) -> list[int]:
    """Какие статьи достать заранее: верх каждой темы в каждом регионе, по убыванию «горячести»."""
    picked: dict[int, float] = {}
    for region in REGIONS:
        sections = collector.build_sections([dict(p) for p in pool], list(TOPICS), [], region, limit=per_topic)
        for s in sections:
            for rank, p in enumerate(s["items"]):
                picked[p["id"]] = max(picked.get(p["id"], -1e9), p["hot"] - rank * 0.01)
    return [i for i, _ in sorted(picked.items(), key=lambda x: -x[1])][:limit]


async def fetch_articles(ids: list[int], concurrency: int = 8) -> dict[int, dict]:
    sem = asyncio.Semaphore(concurrency)
    out: dict[int, dict] = {}

    async def one(i: int):
        async with sem:
            try:
                data = await reader.get_article(i)
            except Exception as e:  # noqa: BLE001
                log.info("Статья %s: %s", i, e)
                return
            if data and data.get("content"):
                out[i] = data

    await asyncio.gather(*(one(i) for i in ids))
    return out


def write_site(out_dir: Path, pool: list[dict], articles: dict[int, dict], updated_at: int | None,
               status: dict) -> dict:
    """Записывает готовый сайт в out_dir (папка очищается)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)

    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("<script>", STATIC_FLAG + "\n<script>", 1)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")   # GitHub Pages: отдавать файлы как есть

    _dump(data_dir / "topics.json",
          {"topics": catalog(), "defaults": DEFAULT_TOPICS, "max": MAX_TOPICS, "regions": REGIONS})
    _dump(data_dir / "sources.json", status)
    weather = {"city": config.WEATHER_CITY, "lat": config.WEATHER_LAT, "lon": config.WEATHER_LON,
               "tz": config.WEATHER_TZ}
    counts = {}
    for region in REGIONS:
        items = [slim(p) for p in region_pool(pool, region)]
        counts[region] = len(items)
        _dump(data_dir / f"news-{region}.json",
              {"updated_at": updated_at, "window_hours": config.WINDOW_HOURS,
               "per_topic": config.PER_TOPIC_LIMIT, "items": items})
    _dump(data_dir / "meta.json", {"updated_at": updated_at, "built_at": int(time.time()),
                                    "weather": weather, "counts": counts, "articles": len(articles)})
    for i, a in articles.items():
        _dump(data_dir / "a" / f"{i}.json", a)
    return {"items": sum(counts.values()), "articles": len(articles), **counts}


async def build(out_dir: Path, refresh: bool = True) -> dict:
    db.init()
    stats = await collector.refresh() if refresh else {"ok": None}
    since = int(time.time() - config.WINDOW_HOURS * 3600)
    pool = db.pool(since)
    ids = article_ids(pool)
    articles = await fetch_articles(ids)
    result = write_site(out_dir, pool, articles, db.last_fetched_at(), collector.load_status())
    log.info("Статический сайт: %s (обновление: %s)", result, stats)
    return {**result, "refresh": stats}
