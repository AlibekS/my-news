"""Настройки. Любой параметр можно переопределить переменной окружения MYNEWS_*."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"MYNEWS_{name}", default)


HOST = _env("HOST", "127.0.0.1")
PORT = int(_env("PORT", "8000"))
DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "data" / "news.db")))
STATIC_DIR = BASE_DIR / "static"

# Как часто фоновый воркер обновляет ленту (часы).
REFRESH_INTERVAL_HOURS = float(_env("REFRESH_INTERVAL_HOURS", "3"))

# Порог внимания: проходит публикация, у которой > MIN_COMMENTS комментариев
# ИЛИ > MIN_SCORE апвоутов/поинтов.
MIN_COMMENTS = int(_env("MIN_COMMENTS", "100"))
MIN_SCORE = int(_env("MIN_SCORE", "250"))

# Сколько новостей на категорию показывать (ТЗ: 7–10).
PER_CATEGORY_LIMIT = int(_env("PER_CATEGORY_LIMIT", "8"))

# Окно свежести: учитываются публикации за последние N часов.
WINDOW_HOURS = float(_env("WINDOW_HOURS", "24"))

# Если «горячих» новостей в категории меньше этого числа — добираем из RSS.
RSS_FALLBACK_MIN = int(_env("RSS_FALLBACK_MIN", "3"))

# Reddit JSON API работает без ключей, но требует осмысленный User-Agent.
USER_AGENT = _env(
    "USER_AGENT",
    "python:my-news-dashboard:1.0 (personal localhost news reader)",
)
HTTP_TIMEOUT = float(_env("HTTP_TIMEOUT", "15"))

CATEGORIES = {
    "games": "Игры",
    "hardware": "Железо",
    "ai": "ИИ",
}

REDDIT_SUBS = {
    "games": ["Games", "pcgaming"],
    "hardware": ["hardware", "buildapc"],
    "ai": ["LocalLLaMA", "MachineLearning"],
}

RSS_FEEDS = {
    "games": [
        ("Rock Paper Shotgun", "https://www.rockpapershotgun.com/feed"),
        ("Eurogamer", "https://www.eurogamer.net/feed"),
    ],
    "hardware": [
        ("Tom's Hardware", "https://www.tomshardware.com/feeds/all"),
        ("VideoCardz", "https://videocardz.com/feed"),
        ("AnandTech", "https://www.anandtech.com/rss/"),
    ],
    "ai": [
        ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ],
}

# Трекер релизов моделей: Hugging Face trending (лайки как метрика внимания).
HF_TRENDING_ENABLED = _env("HF_TRENDING", "1") == "1"
HF_MIN_LIKES = int(_env("HF_MIN_LIKES", "100"))
