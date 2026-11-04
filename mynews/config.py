"""Настройки. Любой параметр можно переопределить переменной окружения MYNEWS_*
или строкой в файле .env в корне проекта (например: MYNEWS_PORT=8080)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"MYNEWS_{name}", default)


HOST = _env("HOST", "127.0.0.1")
PORT = int(_env("PORT", "8000"))
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / "news.db")))
STATUS_PATH = DATA_DIR / "sources.json"
STATIC_DIR = BASE_DIR / "static"

# Как часто фоновый воркер обновляет ленту (часы).
REFRESH_INTERVAL_HOURS = float(_env("REFRESH_INTERVAL_HOURS", "3"))

# Новости старше этого окна в выдачу не попадают (часы).
WINDOW_HOURS = float(_env("WINDOW_HOURS", "36"))

# Сколько новостей показывать в каждой теме.
PER_TOPIC_LIMIT = int(_env("PER_TOPIC_LIMIT", "9"))

# Hacker News: берём англоязычные истории, набравшие больше N поинтов.
HN_ENABLED = _env("HN", "1") == "1"
HN_MIN_POINTS = int(_env("HN_MIN_POINTS", "150"))

USER_AGENT = _env(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; VolnaNewsReader/2.0; personal localhost RSS reader)",
)
HTTP_TIMEOUT = float(_env("HTTP_TIMEOUT", "15"))

# Виджет погоды (Open-Meteo, без ключа).
WEATHER_CITY = _env("WEATHER_CITY", "Астана")
WEATHER_LAT = float(_env("WEATHER_LAT", "51.1694"))
WEATHER_LON = float(_env("WEATHER_LON", "71.4491"))
WEATHER_TZ = _env("WEATHER_TZ", "Asia/Almaty")
