"""SQLite-хранилище: один файл news.db, одна таблица news."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT UNIQUE NOT NULL,   -- reddit:abc123 / hn:123 / rss:<url>
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,                   -- короткое описание / selftext
    image_url       TEXT,
    source_url      TEXT,                   -- первоисточник
    discussion_url  TEXT,                   -- тред Reddit/HN
    source          TEXT,                   -- r/hardware, Hacker News, ...
    comments_count  INTEGER NOT NULL DEFAULT 0,
    score           INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,       -- unix time публикации
    fetched_at      INTEGER NOT NULL,       -- unix time последнего обновления
    content         TEXT,                   -- кэш очищенного текста статьи
    tldr            TEXT                    -- кэш TL;DR (JSON-массив)
);
CREATE INDEX IF NOT EXISTS idx_news_category ON news(category, comments_count DESC);
"""

FIELDS = (
    "external_id", "category", "title", "summary", "image_url", "source_url",
    "discussion_url", "source", "comments_count", "score", "created_at",
)


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
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
        conn.executescript(SCHEMA)


def all_rows() -> list[dict]:
    with connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM news")]


def list_news(categories: list[str] | None = None) -> list[dict]:
    sql = (
        "SELECT id, category, title, summary, image_url, source_url, discussion_url, "
        "source, comments_count, score, created_at FROM news"
    )
    args: list = []
    if categories:
        sql += f" WHERE category IN ({','.join('?' * len(categories))})"
        args = list(categories)
    sql += " ORDER BY comments_count DESC, score DESC"
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def get(news_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM news WHERE id = ?", (news_id,)).fetchone()
        return dict(row) if row else None


def last_fetched_at() -> int | None:
    with connection() as conn:
        row = conn.execute("SELECT MAX(fetched_at) FROM news").fetchone()
        return row[0] if row and row[0] else None


def replace_selection(items: list[dict]) -> None:
    """Сохраняет текущую выборку: обновляет/вставляет items, удаляет всё остальное.

    Кэш текста статьи (content/tldr) у уже существующих записей сохраняется.
    """
    now = int(time.time())
    with connection() as conn:
        keep = []
        for it in items:
            values = [it.get(f) for f in FIELDS]
            conn.execute(
                f"""INSERT INTO news ({','.join(FIELDS)}, fetched_at)
                    VALUES ({','.join('?' * len(FIELDS))}, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                    {', '.join(f'{f}=excluded.{f}' for f in FIELDS[1:])},
                    fetched_at=excluded.fetched_at""",
                values + [now],
            )
            keep.append(it["external_id"])
        if keep:
            conn.execute(
                f"DELETE FROM news WHERE external_id NOT IN ({','.join('?' * len(keep))})",
                keep,
            )
        else:
            conn.execute("DELETE FROM news")


def save_article(news_id: int, content: str, tldr: list[str], image_url: str | None) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE news SET content = ?, tldr = ?, image_url = COALESCE(image_url, ?) WHERE id = ?",
            (content, json.dumps(tldr, ensure_ascii=False), image_url, news_id),
        )
