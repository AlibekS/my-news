"""SQLite-хранилище: один файл news.db, одна таблица articles (пул новостей за окно)."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT UNIQUE NOT NULL,   -- канонический URL статьи
    topics          TEXT NOT NULL,          -- ",ai,hardware," (может быть пустой: ",")
    title           TEXT NOT NULL,
    summary         TEXT,
    image_url       TEXT,                   -- NULL = не искали, '' = картинки нет
    source_url      TEXT,
    discussion_url  TEXT,                   -- тред обсуждения (HN), если есть
    source          TEXT,
    lang            TEXT,                   -- язык заголовка: ru / en
    region          TEXT NOT NULL DEFAULT 'ru', -- ru / en / kz (кнопки на сайте)
    comments_count  INTEGER NOT NULL DEFAULT 0,
    score           INTEGER NOT NULL DEFAULT 0,
    weight          REAL NOT NULL DEFAULT 0,
    also            TEXT,                   -- JSON: [{"source":..., "url":...}] — кто ещё написал
    created_at      INTEGER NOT NULL,
    fetched_at      INTEGER NOT NULL,
    content         TEXT,                   -- кэш очищенного текста
    tldr            TEXT                    -- кэш TL;DR (JSON)
);
"""

FIELDS = (
    "external_id", "topics", "title", "summary", "image_url", "source_url", "discussion_url",
    "source", "lang", "region", "comments_count", "score", "weight", "also", "created_at",
)
LIST_FIELDS = (
    "id", "topics", "title", "summary", "image_url", "source_url", "discussion_url", "source",
    "lang", "region", "comments_count", "score", "weight", "also", "created_at",
)


def _connect() -> sqlite3.Connection:
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connection() as conn:
        conn.execute("DROP TABLE IF EXISTS news")  # таблица первой версии
        cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
        if cols and not set(FIELDS) <= cols:
            conn.execute("DROP TABLE articles")  # схема устарела — это лишь кэш, соберём заново
        conn.executescript(SCHEMA)


def to_item(row: dict) -> dict:
    """Строка БД → элемент конвейера (topics/also раскрыты)."""
    item = {f: row.get(f) for f in FIELDS}
    item["topics"] = [t for t in (row.get("topics") or "").split(",") if t]
    item["also"] = json.loads(row["also"]) if row.get("also") else []
    return item


def all_items() -> list[dict]:
    with connection() as conn:
        return [to_item(dict(r)) for r in conn.execute("SELECT * FROM articles")]


def pool(since: int) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            f"SELECT {','.join(LIST_FIELDS)} FROM articles WHERE created_at >= ?", (since,)
        )
        out = []
        for r in rows:
            d = dict(r)
            d["topics"] = [t for t in d["topics"].split(",") if t]
            d["also"] = json.loads(d["also"]) if d["also"] else []
            out.append(d)
        return out


def get(article_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None


def last_fetched_at() -> int | None:
    with connection() as conn:
        row = conn.execute("SELECT MAX(fetched_at) FROM articles").fetchone()
        return row[0] if row and row[0] else None


def replace_pool(items: list[dict]) -> None:
    """Сохраняет пул: upsert всех items, удаление остального. Кэш текста сохраняется."""
    now = int(time.time())
    with connection() as conn:
        conn.execute("CREATE TEMP TABLE keep (external_id TEXT PRIMARY KEY)")
        for it in items:
            row = dict(it)
            row["topics"] = "," + ",".join(it.get("topics") or []) + ","
            row["also"] = json.dumps(it.get("also") or [], ensure_ascii=False)
            values = [row.get(f) for f in FIELDS]
            conn.execute(
                f"""INSERT INTO articles ({','.join(FIELDS)}, fetched_at)
                    VALUES ({','.join('?' * len(FIELDS))}, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                    {', '.join(f'{f}=excluded.{f}' for f in FIELDS[1:] if f != 'image_url')},
                    image_url=COALESCE(excluded.image_url, articles.image_url),
                    fetched_at=excluded.fetched_at""",
                values + [now],
            )
            conn.execute("INSERT OR IGNORE INTO keep VALUES (?)", (it["external_id"],))
        conn.execute("DELETE FROM articles WHERE external_id NOT IN (SELECT external_id FROM keep)")
        conn.execute("DROP TABLE keep")


def save_article(article_id: int, content: str, tldr: list[str], image_url: str | None) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE articles SET content = ?, tldr = ?, "
            "image_url = CASE WHEN COALESCE(image_url, '') = '' THEN ? ELSE image_url END WHERE id = ?",
            (content, json.dumps(tldr, ensure_ascii=False), image_url, article_id),
        )
