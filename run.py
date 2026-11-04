#!/usr/bin/env python3
"""Запуск: python run.py  →  http://127.0.0.1:8000 (браузер откроется сам)."""
import logging
import os
import threading
import webbrowser

import uvicorn

from mynews import config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # не печатать каждый запрос
    url = f"http://127.0.0.1:{config.PORT}"
    print(f"\n  🌊 Волна запущена: {url}\n  Остановить: Ctrl+C\n")
    if os.environ.get("MYNEWS_OPEN_BROWSER", "1") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("mynews.server:app", host=config.HOST, port=config.PORT, log_level="warning")
