#!/usr/bin/env python3
"""Собрать статическую версию «Волны» для GitHub Pages.

    python tools/build_site.py              # обновить ленты и собрать сайт в ./site
    python tools/build_site.py --no-refresh # собрать из того, что уже есть в data/news.db
    python tools/build_site.py --out public

Открыть результат локально: python -m http.server -d site 8001 → http://127.0.0.1:8001
Обычный режим с сервером (python run.py) от этого не меняется.
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mynews import static_site  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="site", help="папка для сайта (будет очищена)")
    ap.add_argument("--no-refresh", action="store_true", help="не опрашивать ленты, взять из базы")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    result = asyncio.run(static_site.build(Path(args.out), refresh=not args.no_refresh))
    print(result)
    if not result["items"]:
        print("Лента пуста — сайт не публикуем", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
