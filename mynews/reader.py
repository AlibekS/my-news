"""Режим чтения: извлечение чистого текста статьи и построение TL;DR.

Текст вытаскивает trafilatura (вырезает рекламу, меню, верстку). TL;DR строится
экстрактивно — выбираются 3–5 самых «весомых» предложений, без внешних API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import Counter

import trafilatura

from . import collector, db

log = logging.getLogger("mynews.reader")

MAX_CONTENT_CHARS = 12_000
NON_ARTICLE_HOSTS = ("v.redd.it", "i.redd.it", "youtube.com", "youtu.be", "x.com", "twitter.com")

STOP = collector.STOPWORDS | set(
    """also but if so do does did would could should may might there here then them
    which while when where all any some such only very much many one two its it's
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну ли если уже
    или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
    может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего
    раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь
    этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при""".split()
)
WORD_RX = re.compile(r"[\w'-]+", re.U)
SENT_SPLIT_RX = re.compile(r"(?<=[.!?…])[\"”»)]?\s+(?=[\"“«(]?[A-ZА-ЯЁ0-9])")


def split_sentences(text: str) -> list[str]:
    sentences = []
    for para in re.split(r"\n+", text):
        para = para.strip()
        if para:
            sentences += [s.strip() for s in SENT_SPLIT_RX.split(para) if s.strip()]
    return sentences


def summarize(text: str, title: str = "", n: int = 4) -> list[str]:
    """Экстрактивный TL;DR: топ-n предложений в исходном порядке."""
    sentences = split_sentences(text)
    candidates = [
        (i, s) for i, s in enumerate(sentences)
        if 40 <= len(s) <= 400 and not s.endswith(":") and not s.lower().startswith(("image", "photo", "credit"))
    ]
    if len(candidates) <= n:
        return [s for _, s in candidates] or sentences[:n]

    def words(s: str) -> list[str]:
        # грубый стемминг (первые 6 букв), чтобы «видеокарта/видеокарту» считались одним словом
        return [w.lower().replace("ё", "е")[:6] for w in WORD_RX.findall(s) if w.lower() not in STOP and len(w) > 2]

    freq = Counter(w for _, s in candidates for w in words(s))
    if not freq:
        return [s for _, s in candidates[:n]]
    top = max(freq.values())
    title_words = set(words(title))
    total = len(sentences)

    scored = []
    for i, s in candidates:
        ws = words(s)
        if not ws:
            continue
        score = sum(freq[w] / top for w in ws) / math.sqrt(len(ws))
        score += 0.3 * len(title_words & set(ws))
        score *= 1.25 if i < max(3, total * 0.15) else 1.0  # лид статьи важнее
        scored.append((score, i, s))
    best = sorted(scored, reverse=True)[:n]
    return [s for _, _, s in sorted(best, key=lambda t: t[1])]


def _extract(html_text: str, url: str) -> tuple[str, str | None]:
    text = trafilatura.extract(
        html_text, url=url, include_comments=False, include_tables=False, favor_precision=True
    ) or ""
    image = None
    try:
        meta = trafilatura.extract_metadata(html_text, default_url=url)
        image = getattr(meta, "image", None) if meta else None
    except Exception:  # noqa: BLE001
        pass
    return text, image


def _clean_reddit_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"[*_#>`]{1,3}", "", text)
    return re.sub(r"&amp;#x200B;|​", "", text).strip()


async def get_article(news_id: int) -> dict | None:
    item = db.get(news_id)
    if not item:
        return None
    if item.get("tldr"):
        return {"id": news_id, "tldr": json.loads(item["tldr"]), "content": item.get("content") or "",
                "image_url": item.get("image_url")}

    url = item.get("source_url") or ""
    text, image = "", None
    is_thread = url == item.get("discussion_url")
    if url and not is_thread and not any(h in url for h in NON_ARTICLE_HOSTS):
        try:
            async with collector.make_client() as client:
                r = await client.get(url, timeout=12)
                if r.status_code < 400 and "html" in r.headers.get("content-type", "html"):
                    text, image = await asyncio.to_thread(_extract, r.text, url)
        except Exception as e:  # noqa: BLE001
            log.info("Не удалось загрузить %s: %s", url, e)

    if len(text) < 200 and item.get("summary"):
        text = _clean_reddit_markdown(item["summary"])

    text = text[:MAX_CONTENT_CHARS]
    tldr = summarize(text, item["title"]) if text else []
    if text:
        db.save_article(news_id, text, tldr, image)
    return {"id": news_id, "tldr": tldr, "content": text, "image_url": item.get("image_url") or image}
