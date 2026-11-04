#!/usr/bin/env python3
"""Запуск: python run.py  →  http://127.0.0.1:8000"""
import logging

import uvicorn

from mynews import config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("mynews.server:app", host=config.HOST, port=config.PORT, log_level="warning")
