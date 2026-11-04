"""Поиск по интернету и чтение любой статьи внутри сайта.

Поиск работает без API-ключей:
  1. DuckDuckGo (HTML-версия, регион ru-ru);
  2. если он не ответил или дал мало результатов — Bing в формате RSS.
Результаты склеиваются, дубли убираются, русскоязычные идут первыми.
Сверху добавляются совпадения из собственной ленты.

Чтение: страница скачивается, trafilatura вычищает рекламу и вёрстку, краткое
содержание строится тем же алгоритмом, что и для новостей ленты.
"""
from __future__ import annotations

import asyncio
import calendar
import html
import ipaddress
import logging
import re
import socket
import time
from collections import OrderedDict
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

import feedparser
import httpx
import trafilatura

from . import collector, config, db, reader

log = logging.getLogger("mynews.search")

# Поисковики отдают нормальную выдачу обычному браузеру.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class TTLCache:
    def __init__(self, size: int, ttl: float):
        self.size, self.ttl, self.data = size, ttl, OrderedDict()

    def get(self, key):
        v = self.data.get(key)
        if v and time.time() - v[0] < self.ttl:
            self.data.move_to_end(key)
            return v[1]
        return None

    def set(self, key, value):
        self.data[key] = (time.time(), value)
        self.data.move_to_end(key)
        while len(self.data) > self.size:
            self.data.popitem(last=False)


_search_cache = TTLCache(100, 10 * 60)
_read_cache = TTLCache(100, 60 * 60)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


# --------------------------------------------------------------------------- #
# DuckDuckGo
# --------------------------------------------------------------------------- #
DDG_BLOCK_RX = re.compile(r'<div[^>]+class="[^"]*\bresult\b[^"]*"', re.I)
DDG_LINK_RX = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
DDG_SNIPPET_RX = re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:a|div|td)>', re.I | re.S)


def _ddg_url(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        target = parse_qs(urlsplit(href).query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def parse_ddg(page: str) -> list[dict]:
    out = []
    starts = [m.start() for m in DDG_BLOCK_RX.finditer(page)] + [len(page)]
    for a, b in zip(starts, starts[1:]):
        block = page[a:b]
        if "result--ad" in block[:300]:
            continue
        link = DDG_LINK_RX.search(block)
        if not link:
            continue
        url = _ddg_url(link.group(1))
        if not url.startswith("http") or "duckduckgo.com" in url:
            continue
        snip = DDG_SNIPPET_RX.search(block)
        out.append({"title": _clean(link.group(2)), "url": url, "snippet": _clean(snip.group(1)) if snip else ""})
    return out


async def search_ddg(client: httpx.AsyncClient, q: str) -> list[dict]:
    r = await client.get(f"https://html.duckduckgo.com/html/?q={quote_plus(q)}&kl=ru-ru",
                         headers={"User-Agent": BROWSER_UA, "Accept-Language": "ru,en;q=0.7"})
    r.raise_for_status()
    return parse_ddg(r.text)


# --------------------------------------------------------------------------- #
# Bing (RSS)
# --------------------------------------------------------------------------- #
def parse_bing_rss(content: bytes) -> list[dict]:
    feed = feedparser.parse(content)
    out = []
    for e in feed.entries:
        if e.get("link") and e.get("title"):
            ts = e.get("published_parsed")
            out.append({"title": _clean(e.title), "url": e.link, "snippet": _clean(e.get("summary", "")),
                        "date": calendar.timegm(ts) if ts else None})
    return out


async def search_bing(client: httpx.AsyncClient, q: str) -> list[dict]:
    r = await client.get(f"https://www.bing.com/search?format=rss&q={quote_plus(q)}&setlang=ru&cc=RU&count=20",
                         headers={"User-Agent": BROWSER_UA, "Accept-Language": "ru,en;q=0.7"})
    r.raise_for_status()
    return parse_bing_rss(r.content)


# --------------------------------------------------------------------------- #
# Поиск по своей ленте
# --------------------------------------------------------------------------- #
def search_local(q: str, limit: int = 4) -> list[dict]:
    terms = [t[:5] for t in collector.title_tokens(q)]
    if not terms:
        return []
    since = int(time.time() - config.WINDOW_HOURS * 3600)
    found = []
    for p in db.pool(since):
        text = (p["title"] + " " + (p.get("summary") or "")[:600]).lower().replace("ё", "е")
        hits = sum(1 for t in terms if t in text)
        if hits == len(terms) or (len(terms) >= 3 and hits >= len(terms) - 1):
            found.append((hits, collector.hotness(p), p))
    found.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [p for _, _, p in found[:limit]]


def rank(results: list[dict]) -> list[dict]:
    """Убирает дубли; русскоязычные результаты — выше (порядок поисковика сохраняется)."""
    seen, uniq = set(), []
    for r in results:
        key = collector.canonical_url(r["url"])
        if key and key not in seen:
            seen.add(key)
            r["source"] = host_of(r["url"])
            r["lang"] = collector.detect_lang(r["title"] + " " + r.get("snippet", ""))
            uniq.append(r)
    return sorted(uniq, key=lambda r: r["lang"] != "ru")  # sorted() стабилен


async def search(q: str) -> dict:
    q = q.strip()[:200]
    if not q:
        return {"query": q, "local": [], "web": [], "engine": None}
    cached = _search_cache.get(q.lower())
    if cached:
        return cached
    web, engines, errors = [], [], []
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for name, fn in (("DuckDuckGo", search_ddg), ("Bing", search_bing)):
            try:
                found = await fn(client, q)
                if found:
                    web += found
                    engines.append(name)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {str(e).splitlines()[0][:120]}")
                log.warning("Поиск %s: %s", name, e)
            if len(web) >= 8:
                break
    local = search_local(q)
    data = {"query": q, "local": local, "web": rank(web)[:15], "engine": " + ".join(engines) or None,
            "errors": errors if not web else []}
    if web:
        _search_cache.set(q.lower(), data)
    return data


# --------------------------------------------------------------------------- #
# Чтение любой статьи
# --------------------------------------------------------------------------- #
class BadURL(ValueError):
    pass


def check_url(url: str) -> str:
    """Разрешаем только обычные публичные http(s)-адреса (не локальную сеть)."""
    p = urlsplit(url.strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BadURL("Нужна ссылка вида https://…")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror:
        raise BadURL("Сайт не найден") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BadURL("Адреса локальной сети открывать нельзя")
    return url.strip()


def _extract_full(page: str, url: str) -> dict:
    text = trafilatura.extract(page, url=url, include_comments=False, include_tables=False, favor_precision=True) or ""
    meta = None
    try:
        meta = trafilatura.extract_metadata(page, default_url=url)
    except Exception:  # noqa: BLE001
        pass
    created = None
    if meta and getattr(meta, "date", None):
        try:
            created = calendar.timegm(time.strptime(meta.date[:10], "%Y-%m-%d"))
        except ValueError:
            pass
    return {
        "content": text,
        "title": (getattr(meta, "title", None) or "").strip(),
        "image_url": getattr(meta, "image", None),
        "site": getattr(meta, "sitename", None),
        "created_at": created,
    }


async def read_url(url: str) -> dict:
    url = await asyncio.to_thread(check_url, url)
    cached = _read_cache.get(url)
    if cached:
        return cached
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": BROWSER_UA, "Accept-Language": "ru,en;q=0.7"}) as client:
        r = await client.get(url)
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "html"):
            raise BadURL("Это не веб-страница")
        data = await asyncio.to_thread(_extract_full, r.text[:3_000_000], str(r.url))
    content = data["content"][:reader.MAX_CONTENT_CHARS]
    title = data["title"] or host_of(url)
    result = {
        "url": url, "title": title, "content": content,
        "tldr": reader.summarize(content, title) if content else [],
        "image_url": data["image_url"], "source": data["site"] or host_of(url),
        "created_at": data["created_at"],
    }
    _read_cache.set(url, result)
    return result
