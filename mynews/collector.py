"""Сбор, классификация, дедупликация и ранжирование новостей.

Прогон обновления:
  1. Параллельно читаем все RSS-ленты из topics.py (+ Hacker News).
  2. Раскладываем новости по темам: лента темы + ключевые слова в заголовке.
  3. Сливаем со свежими записями из БД (если лента временно не ответила,
     её новости не пропадают до конца окна).
  4. Склеиваем дубли: одна и та же новость с разных сайтов становится одной
     карточкой — приоритет у русскоязычного источника, остальные попадают в
     «Также пишут», а их число поднимает новость в рейтинге.
  5. Для верхних новостей каждой темы подтягиваем превью (og:image).

Рейтинг («горячесть») считается при выдаче: свежесть + сколько сайтов написали
об этом + обсуждаемость (комментарии/поинты, где они есть) + вес ленты.
"""
from __future__ import annotations

import asyncio
import calendar
import html
import json
import logging
import math
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx

from . import config, db
from .topics import REGIONS, TOPICS, all_feeds

log = logging.getLogger("mynews.collector")

Item = dict

# --------------------------------------------------------------------------- #
# Ключевые слова
# --------------------------------------------------------------------------- #
def _keyword_pattern(keyword: str) -> str:
    words = keyword.strip().lower().split()
    parts = []
    for w in words:
        if w.endswith("$"):
            parts.append(re.escape(w[:-1]) + r"(?!\w)")
        else:
            parts.append(re.escape(w) + r"\w*")
    return r"(?<!\w)" + r"\s+".join(parts)


def compile_matcher(keywords: list[str], acronyms: list[str] | None = None) -> list[re.Pattern]:
    patterns = []
    kws = [k for k in keywords if k.strip()]
    if kws:
        patterns.append(re.compile("|".join(_keyword_pattern(k) for k in kws), re.I))
    acr = [a for a in (acronyms or []) if a.strip()]
    if acr:
        patterns.append(re.compile(r"(?<!\w)(?:" + "|".join(re.escape(a) for a in acr) + r")(?!\w)"))
    return patterns


def count_hits(patterns: list[re.Pattern], text: str) -> int:
    return sum(len(p.findall(text)) for p in patterns)


MATCHERS = {k: compile_matcher(t["keywords"], t.get("acronyms")) for k, t in TOPICS.items()}


def classify(title: str, summary: str = "", feed: dict | None = None) -> list[str]:
    """Темы новости, от самой подходящей к менее подходящей.

    Тема подходит, если её ключевое слово есть в заголовке, или ≥2 совпадения в начале
    описания. Порядок — по силе совпадения (заголовок весит вдвое больше описания);
    тема «своей» ленты получает небольшой бонус, но не перебивает явное совпадение:
    новость про смартфон из ленты «Железо» окажется в первую очередь в «Гаджетах».
    """
    lead = (summary or "")[:400]
    scores: dict[str, float] = {}
    for key, pats in MATCHERS.items():
        th, lh = count_hits(pats, title), count_hits(pats, lead)
        if th >= 1 or lh >= 2:
            scores[key] = 2 * th + 0.5 * lh
    if feed and feed.get("topic"):
        t, mode = feed["topic"], feed.get("mode", "bound")
        if mode == "bound":
            scores[t] = scores.get(t, 0) + 1.5
        elif mode == "fallback" and not scores:
            scores[t] = 1
    order = list(MATCHERS)
    return sorted(scores, key=lambda k: (-scores[k], order.index(k)))


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    if not host:
        return None
    query = p.query if "news.ycombinator.com" in host else ""
    return urlunsplit(("", host, p.path.rstrip("/"), query, ""))[2:]


def detect_lang(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    cyr = sum(1 for c in letters if "а" <= c.lower() <= "я" or c in "ёЁ")
    return "ru" if cyr / len(letters) > 0.3 else "en"


def strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


IMG_RX = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


# --------------------------------------------------------------------------- #
# Источники
# --------------------------------------------------------------------------- #
def parse_feed(content: bytes, feed: dict) -> list[Item]:
    parsed = feedparser.parse(content)
    items = []
    for e in parsed.entries:
        link = e.get("link")
        title = strip_html(e.get("title", "")).replace("\n", " ")
        if not link or not title:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        created = calendar.timegm(ts) if ts else int(time.time())
        raw = e.get("summary", "")
        if e.get("content"):
            raw = max((c.get("value", "") for c in e.content), key=len, default=raw) or raw
        summary = strip_html(raw)
        image = None
        for key in ("media_content", "media_thumbnail"):
            media = e.get(key)
            if media and media[0].get("url") and "image" in media[0].get("type", "image"):
                image = media[0]["url"]
                break
        if not image:
            for enc in e.get("enclosures", []):
                if str(enc.get("type", "")).startswith("image") and enc.get("href"):
                    image = enc["href"]
                    break
        if not image:
            m = IMG_RX.search(raw)
            if m and not m.group(1).startswith("data:"):
                image = html.unescape(m.group(1))
        ext = canonical_url(link)
        if not ext:
            continue
        comments = str(e.get("slash_comments", ""))
        items.append({
            "external_id": ext,
            "topics": classify(title, summary, feed),
            "title": title,
            "summary": summary[:1500] or None,
            "image_url": image,
            "source_url": link,
            "discussion_url": None,
            "source": feed["name"],
            "lang": detect_lang(title),
            "region": feed.get("region", "ru"),
            "comments_count": int(comments) if comments.isdigit() else 0,
            "score": 0,
            "weight": float(feed.get("weight", 0)),
            "also": [],
            "created_at": int(min(created, time.time())),
        })
    return items


def parse_hn(payload: dict) -> list[Item]:
    items = []
    for hit in payload.get("hits", []):
        title = (hit.get("title") or "").strip()
        topics = classify(title)
        if not title or not topics:
            continue
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        url = hit.get("url") or discussion
        items.append({
            "external_id": canonical_url(url),
            "topics": topics,
            "title": title,
            "summary": strip_html(hit.get("story_text") or "") or None,
            "image_url": None,
            "source_url": url,
            "discussion_url": discussion,
            "source": "Hacker News",
            "lang": "en",
            "region": "en",
            "comments_count": int(hit.get("num_comments") or 0),
            "score": int(hit.get("points") or 0),
            "weight": 0.0,
            "also": [],
            "created_at": int(hit.get("created_at_i") or time.time()),
        })
    return items


ALT_RX = re.compile(r"""<link[^>]+type=["']application/(?:rss|atom)\+xml["'][^>]*>""", re.I)
HREF_RX = re.compile(r"""href=["']([^"']+)["']""", re.I)


def discover_feed_url(page: str, base: str) -> str | None:
    """Ищет на HTML-странице ссылку на RSS/Atom (<link rel="alternate" ...>)."""
    for m in ALT_RX.finditer(page):
        tag = m.group(0)
        if "comments" in tag.lower():
            continue
        href = HREF_RX.search(tag)
        if href:
            return urljoin(base, html.unescape(href.group(1)))
    return None


def _looks_like_html(content: bytes) -> bool:
    head = content[:2000].lower()
    return b"<html" in head or b"<!doctype html" in head


async def _fetch_one(client: httpx.AsyncClient, url: str, feed: dict) -> tuple[list[Item], str]:
    r = await client.get(url)
    r.raise_for_status()
    if _looks_like_html(r.content):
        found = discover_feed_url(r.text[:300_000], str(r.url))
        if not found:
            raise ValueError("на странице не найдена RSS-лента")
        url = found
        r = await client.get(url)
        r.raise_for_status()
    items = await asyncio.to_thread(parse_feed, r.content, feed)
    if not items:
        raise ValueError("лента пуста или это не RSS")
    return items, url


async def fetch_feed(client: httpx.AsyncClient, feed: dict, sem: asyncio.Semaphore) -> tuple[list[Item], dict]:
    """Пробует адреса ленты по очереди, пока один не ответит."""
    status = {"name": feed["name"], "url": feed["urls"][0], "topic": feed.get("topic"),
              "region": feed.get("region", "ru"), "ok": False, "count": 0}
    errors = []
    async with sem:
        for url in feed["urls"]:
            try:
                items, used = await _fetch_one(client, url, feed)
                status.update(ok=True, count=len(items), url=used)
                return items, status
            except Exception as e:  # noqa: BLE001
                errors.append(str(e).split("\n")[0][:160])
    status["error"] = errors[-1] if errors else "нет адресов"
    log.warning("Лента «%s» не ответила: %s", feed["name"], status["error"])
    return [], status


async def fetch_hn(client: httpx.AsyncClient) -> tuple[list[Item], dict]:
    status = {"name": "Hacker News", "url": "https://news.ycombinator.com", "topic": None,
              "region": "en", "ok": False, "count": 0}
    since = int(time.time() - config.WINDOW_HOURS * 3600)
    url = ("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=300"
           f"&numericFilters=created_at_i>{since},points>{config.HN_MIN_POINTS}")
    try:
        r = await client.get(url)
        r.raise_for_status()
        items = parse_hn(r.json())
        status.update(ok=True, count=len(items))
        return items, status
    except Exception as e:  # noqa: BLE001
        status["error"] = str(e).split("\n")[0][:200]
        log.warning("Hacker News не ответил: %s", status["error"])
        return [], status


# --------------------------------------------------------------------------- #
# Дедупликация
# --------------------------------------------------------------------------- #
STOPWORDS = set(
    """a an the and or of to in on for with from by at as is are was were be been it its this that
    new now just how why what who will can has have had not no you your we our they their about
    after over into than more most up out first says said report reportedly show ask vs via
    и в во не что на с со как а то все так но да к у же за бы по только из о от для до при
    это этот эта эти уже или ни был была было были будет может могут свой своя свои его ее их
    новый новая новое новые новым новой новую нового новых стал стала стало теперь также ещё еще""".split()
)
TOKEN_RX = re.compile(r"[a-zа-яё0-9]+(?:[.\-][a-zа-яё0-9]+)*", re.I)


STEM = 5


def title_tokens(title: str) -> set[str]:
    out = set()
    for t in TOKEN_RX.findall(title.lower().replace("ё", "е")):
        if t in STOPWORDS or (len(t) < 3 and not t.isdigit()):
            continue
        out.add(t[:STEM] if t.isalpha() else t)  # грубый стемминг: «долгих» ≈ «долгим»
    return out


def _has_digit(t: str) -> bool:
    return any(c.isdigit() for c in t)


def is_duplicate(a: Item, b: Item, ta: set | None = None, tb: set | None = None) -> bool:
    if a["external_id"] == b["external_id"]:
        return True
    ta = ta if ta is not None else title_tokens(a["title"])
    tb = tb if tb is not None else title_tokens(b["title"])
    if not ta or not tb:
        return False
    # Номера моделей различают новости: «RTX 5090» ≠ «RTX 5080».
    da, dbs = {t for t in ta if _has_digit(t)}, {t for t in tb if _has_digit(t)}
    if da and dbs and not (da & dbs):
        return False
    common = len(ta & tb)
    jaccard = common / len(ta | tb)
    overlap = common / min(len(ta), len(tb))
    return (common >= 3 and jaccard >= 0.45) or (common >= 4 and overlap >= 0.6)


def winner_key(item: Item):
    return (
        item.get("lang") == "ru",
        bool(item.get("summary")),
        item.get("weight", 0),
        item.get("comments_count", 0),
        -item.get("created_at", 0),
    )


def deduplicate(items: list[Item]) -> list[Item]:
    """Склеивает одинаковые новости (по ссылке или похожему заголовку).

    Если новость похожа сразу на несколько групп, группы объединяются —
    результат не зависит от порядка, в котором пришли заголовки.
    """
    items = sorted(items, key=winner_key, reverse=True)
    groups: list[dict | None] = []   # {"winner", "members": [(item, tokens)]}
    index: dict[str, set[int]] = {}  # токен/URL → номера групп
    for item in items:
        toks = title_tokens(item["title"])
        keys = toks | {"url:" + item["external_id"]}
        candidates: set[int] = set()
        for k in keys:
            candidates |= index.get(k, set())
        matched = [gi for gi in sorted(candidates)
                   if groups[gi] and any(is_duplicate(m, item, mt, toks) for m, mt in groups[gi]["members"])]
        if not matched:
            gi = len(groups)
            groups.append({"winner": dict(item, also=list(item.get("also") or [])), "members": []})
        else:
            gi = matched[0]
            _merge(groups[gi]["winner"], item)
            for other in matched[1:]:  # объединяем группы, связанные этой новостью
                for m, mt in groups[other]["members"]:
                    _merge(groups[gi]["winner"], m)
                    groups[gi]["members"].append((m, mt))
                    for k in mt | {"url:" + m["external_id"]}:
                        index.setdefault(k, set()).add(gi)
                groups[other] = None
        groups[gi]["members"].append((item, toks))
        for k in keys:
            index.setdefault(k, set()).add(gi)
    return [g["winner"] for g in groups if g]


def _merge(winner: Item, other: Item) -> None:
    seen = {canonical_url(winner["source_url"])} | {canonical_url(a["url"]) for a in winner["also"]}
    for entry in [{"source": other["source"], "url": other["source_url"]}] + list(other.get("also") or []):
        cu = canonical_url(entry["url"])
        if cu not in seen and entry["source"] != winner["source"]:
            winner["also"].append(entry)
            seen.add(cu)
    winner["topics"] = list(dict.fromkeys((winner.get("topics") or []) + (other.get("topics") or [])))
    for field in ("image_url", "summary"):
        if not winner.get(field) and other.get(field):
            winner[field] = other[field]
    if other.get("discussion_url") and other.get("comments_count", 0) >= winner.get("comments_count", 0):
        winner["discussion_url"] = other["discussion_url"]
        winner["comments_count"] = other["comments_count"]
        winner["score"] = max(winner.get("score", 0), other.get("score", 0))


# --------------------------------------------------------------------------- #
# Рейтинг и выдача
# --------------------------------------------------------------------------- #
def hotness(item: dict, now: float | None = None) -> float:
    now = now or time.time()
    age_h = max(0.0, (now - item["created_at"]) / 3600)
    fresh = 3.0 * math.exp(-age_h / 12)
    coverage = 2.5 * len(item.get("also") or [])
    engagement = (1.2 * math.log10(1 + (item.get("comments_count") or 0))
                  + 0.8 * math.log10(1 + (item.get("score") or 0)))
    return fresh + coverage + engagement + (item.get("weight") or 0)


def custom_matcher(keywords: str) -> list[re.Pattern]:
    return compile_matcher([k for k in re.split(r"[,;\n]", keywords or "") if k.strip()])


def build_sections(pool: list[dict], topic_ids: list[str], custom: list[dict], region: str | None,
                   limit: int | None = None) -> list[dict]:
    """Раскладывает пул по темам пользователя; каждая новость показывается один раз.

    Новость попадает в свою самую подходящую тему из выбранных (а не в первую по
    порядку на странице). Свои темы пользователя имеют приоритет: если вы завели
    тему «Apple», новости про iPhone окажутся в ней, а не в «Гаджетах».
    """
    limit = limit or config.PER_TOPIC_LIMIT
    now = time.time()
    if region in REGIONS:
        pool = [p for p in pool if p.get("region") == region]
        if region == "kz":  # казахстанские СМИ — только материалы на русском
            pool = [p for p in pool if p.get("lang") == "ru"]
    for p in pool:
        p["hot"] = round(hotness(p, now), 2)
    ranked = sorted(pool, key=lambda p: p["hot"], reverse=True)

    custom_by_id = {str(c.get("id")): c for c in custom}
    custom_pats = {tid: custom_matcher(custom_by_id[tid].get("keywords", ""))
                   for tid in topic_ids if tid in custom_by_id}
    buckets: dict[str, list] = {tid: [] for tid in topic_ids if tid in TOPICS or tid in custom_pats}

    for p in ranked:
        text = p["title"] + " " + (p.get("summary") or "")[:500]
        target = next((tid for tid, pats in custom_pats.items() if pats and count_hits(pats, text) > 0), None)
        if target is None:
            target = next((t for t in p["topics"] if t in buckets and t in TOPICS), None)
        if target is not None and len(buckets[target]) < limit:
            buckets[target].append(p)
    return [{"topic": tid, "items": buckets[tid]} for tid in topic_ids if tid in buckets]


# --------------------------------------------------------------------------- #
# Превью-картинки
# --------------------------------------------------------------------------- #
OG_RX = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)(?::src)?["'][^>]*>""", re.I)
CONTENT_RX = re.compile(r"""content=["']([^"']+)["']""", re.I)


def extract_og_image(page: str) -> str | None:
    m = OG_RX.search(page)
    if m:
        c = CONTENT_RX.search(m.group(0))
        if c:
            return html.unescape(c.group(1))
    return None


async def enrich_images(client: httpx.AsyncClient, items: list[Item]) -> None:
    sem = asyncio.Semaphore(8)

    async def one(item: Item):
        async with sem:
            try:
                r = await client.get(item["source_url"], timeout=8)
                ctype = r.headers.get("content-type", "")
                item["image_url"] = (extract_og_image(r.text[:300_000]) if "html" in ctype else None) or ""
            except Exception:  # noqa: BLE001
                item["image_url"] = ""

    await asyncio.gather(*(one(i) for i in items if i.get("image_url") is None and i.get("source_url")))


def top_candidates(items: list[Item], per_topic: int) -> list[Item]:
    """Верхние новости каждой темы в каждом регионе — им подтягиваем превью."""
    now = time.time()
    ranked = sorted(items, key=lambda p: hotness(p, now), reverse=True)
    picked: dict[int, Item] = {}
    for region in REGIONS:
        in_region = [p for p in ranked if p.get("region") == region]
        for tid in TOPICS:
            for p in [p for p in in_region if tid in p["topics"]][:per_topic]:
                picked[id(p)] = p
    return list(picked.values())


# --------------------------------------------------------------------------- #
# Прогон
# --------------------------------------------------------------------------- #
_lock = asyncio.Lock()


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": config.USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
    )


def merge_pool(fresh: list[Item], existing: list[Item]) -> list[Item]:
    cutoff = time.time() - config.WINDOW_HOURS * 3600
    by_id: dict[str, Item] = {}
    for item in existing:
        if item["created_at"] >= cutoff:
            by_id[item["external_id"]] = item
    for item in fresh:
        if item["created_at"] >= cutoff:
            prev = by_id.get(item["external_id"])
            if prev and prev.get("image_url") is not None and not item.get("image_url"):
                item["image_url"] = prev["image_url"]
            by_id[item["external_id"]] = item
    # Дубли склеиваются внутри региона: в режиме KZ нужны свои, казахстанские источники.
    out: list[Item] = []
    for region in REGIONS:
        out += deduplicate([i for i in by_id.values() if i["topics"] and i.get("region", "ru") == region])
    return out


def save_status(statuses: list[dict]) -> None:
    config.STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.STATUS_PATH.write_text(
        json.dumps({"checked_at": int(time.time()), "feeds": statuses}, ensure_ascii=False), encoding="utf-8"
    )


def load_status() -> dict:
    try:
        return json.loads(config.STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"checked_at": None, "feeds": []}


async def refresh() -> dict:
    """Полный цикл обновления. Безопасен для параллельного вызова."""
    async with _lock:
        started = time.time()
        async with make_client() as client:
            sem = asyncio.Semaphore(10)
            jobs = [fetch_feed(client, f, sem) for f in all_feeds()]
            if config.HN_ENABLED:
                jobs.append(fetch_hn(client))
            results = await asyncio.gather(*jobs)
            fresh = [i for items, _ in results for i in items]
            statuses = [s for _, s in results]
            save_status(statuses)
            ok = sum(1 for s in statuses if s["ok"])
            if not fresh:
                log.error("Ни одна лента не ответила — лента не изменена")
                return {"ok": False, "sources_ok": 0, "sources_total": len(statuses)}
            items = await asyncio.to_thread(merge_pool, fresh, db.all_items())
            await enrich_images(client, top_candidates(items, config.PER_TOPIC_LIMIT + 3))
        db.replace_pool(items)
        stats = {
            "ok": True, "items": len(items), "sources_ok": ok, "sources_total": len(statuses),
            "seconds": round(time.time() - started, 1),
        }
        log.info("Лента обновлена: %s", stats)
        return stats


def is_running() -> bool:
    return _lock.locked()
