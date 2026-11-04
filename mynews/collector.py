"""Сбор и фильтрация новостей.

Конвейер одного прогона:
  1. Параллельно опрашиваем Reddit (top за сутки), Hacker News, RSS и HF trending.
  2. Оставляем только публикации, преодолевшие порог внимания.
  3. Сливаем со свежими записями из БД (если источник временно недоступен,
     его новости не пропадают до конца окна).
  4. Дедуплицируем: из похожих инфоповодов остаётся вариант с бóльшим
     числом комментариев.
  5. Берём топ-N на категорию, при нехватке добираем свежими RSS-заголовками.
  6. Подтягиваем превью-картинки (og:image) для карточек без изображения.
"""
from __future__ import annotations

import asyncio
import calendar
import html
import logging
import re
import time
from urllib.parse import urlsplit, urlunsplit

import feedparser
import httpx

from . import config, db

log = logging.getLogger("mynews.collector")

Item = dict  # ключи совпадают с колонками таблицы news

# --------------------------------------------------------------------------- #
# Классификация заголовков Hacker News по темам
# --------------------------------------------------------------------------- #
KEYWORDS = {
    "ai": re.compile(
        r"\b(ai|a\.i\.|agi|llms?|gpts?|gpt-\d\w*|chatgpt|openai|anthropic|claude|gemini|"
        r"llama|mistral|deepseek|qwen|grok|transformers?|neural|machine learning|"
        r"deep learning|diffusion|hugging ?face|inference|fine-?tun\w*|rlhf|embeddings?|"
        r"copilot|chatbots?|language models?|reasoning models?|ai agents?|agentic)\b",
        re.I,
    ),
    "hardware": re.compile(
        r"\b(cpus?|gpus?|nvidia|amd|intel|radeon|geforce|rtx|ryzen|threadripper|epyc|"
        r"xeon|risc-v|tsmc|semiconductors?|chips?|chipmakers?|silicon|motherboards?|"
        r"ssds?|nvme|dram|ddr5|hbm|processors?|lithography|asml|qualcomm|snapdragon|"
        r"raspberry pi|fpgas?|m[1-6] (pro|max|ultra)|apple silicon|overclock\w*)\b",
        re.I,
    ),
    "games": re.compile(
        r"\b(video ?games?|games?|gaming|gamers?|steam|valve|nintendo|playstation|ps5|"
        r"xbox|unreal engine|godot|esports|game ?dev|speedrun\w*)\b",
        re.I,
    ),
}
CATEGORY_PRIORITY = ["ai", "hardware", "games"]


def classify(title: str) -> str | None:
    hits = {cat: len(rx.findall(title)) for cat, rx in KEYWORDS.items()}
    best = max(hits.values())
    if best == 0:
        return None
    return next(c for c in CATEGORY_PRIORITY if hits[c] == best)


# --------------------------------------------------------------------------- #
# Порог внимания и дедупликация
# --------------------------------------------------------------------------- #
def passes_threshold(item: Item) -> bool:
    return (
        item.get("comments_count", 0) > config.MIN_COMMENTS
        or item.get("score", 0) > config.MIN_SCORE
    )


STOPWORDS = set(
    """a an the and or of to in on for with from by at as is are was were be been it its
    this that these those new now just how why what who will can has have had not no
    you your we our they their i my he she his her vs via about after over into than
    more most up out first says said report reportedly hn show ask""".split()
)
_TOKEN_RX = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def title_tokens(title: str) -> set[str]:
    toks = _TOKEN_RX.findall(title.lower())
    return {t for t in toks if t not in STOPWORDS and (len(t) > 2 or t.isdigit())}


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    host = p.netloc.lower().removeprefix("www.").removeprefix("old.")
    if not host:
        return None
    return urlunsplit(("", host, p.path.rstrip("/"), "", ""))


def is_duplicate(a: Item, b: Item) -> bool:
    ua, ub = canonical_url(a.get("source_url")), canonical_url(b.get("source_url"))
    # Ссылка на одну и ту же статью (но не на сам тред обсуждения)
    if ua and ua == ub and a.get("source_url") != a.get("discussion_url"):
        return True
    ta, tb = title_tokens(a["title"]), title_tokens(b["title"])
    if not ta or not tb:
        return False
    common = ta & tb
    jaccard = len(common) / len(ta | tb)
    overlap = len(common) / min(len(ta), len(tb))
    return (len(common) >= 3 and jaccard >= 0.5) or (len(common) >= 4 and overlap >= 0.75)


def rank_key(item: Item):
    return (item.get("comments_count", 0), item.get("score", 0))


def deduplicate(items: list[Item]) -> list[Item]:
    """Группирует похожие инфоповоды, оставляя самый обсуждаемый вариант.

    Сравнение идёт со всеми членами группы, поэтому дубли ловятся транзитивно
    (A≈B по заголовку, B≈C по ссылке → одна группа).
    """
    groups: list[tuple[Item, list[Item]]] = []  # (победитель, все члены группы)
    for item in sorted(items, key=rank_key, reverse=True):
        group = next((g for g in groups if any(is_duplicate(m, item) for m in g[1])), None)
        if group is None:
            groups.append((dict(item), [item]))
            continue
        winner, members = group
        members.append(item)
        # Победитель остаётся, но может «позаимствовать» картинку/описание.
        for field in ("image_url", "summary"):
            if not winner.get(field) and item.get(field):
                winner[field] = item[field]
        # Если победитель — тред без внешней ссылки, а у дубля есть статья.
        if winner.get("source_url") == winner.get("discussion_url") and item.get("source_url") \
                and item.get("source_url") != item.get("discussion_url"):
            winner["source_url"] = item["source_url"]
    return [winner for winner, _ in groups]


def select_top(hot: list[Item], rss: list[Item]) -> list[Item]:
    result: list[Item] = []
    for cat in config.CATEGORIES:
        top = sorted((i for i in hot if i["category"] == cat), key=rank_key, reverse=True)
        top = top[: config.PER_CATEGORY_LIMIT]
        if len(top) < config.RSS_FALLBACK_MIN:
            fillers = sorted(
                (i for i in rss if i["category"] == cat and not any(is_duplicate(i, t) for t in hot)),
                key=lambda i: i["created_at"],
                reverse=True,
            )
            top += fillers[: config.RSS_FALLBACK_MIN - len(top)]
        result += top
    return result


# --------------------------------------------------------------------------- #
# Источники
# --------------------------------------------------------------------------- #
REDDIT_MEDIA_HOSTS = ("i.redd.it", "v.redd.it", "reddit.com", "i.imgur.com")
IMAGE_EXT_RX = re.compile(r"\.(jpe?g|png|webp|gif)(\?.*)?$", re.I)


def parse_reddit(payload: dict, category: str, sub: str) -> list[Item]:
    items = []
    for child in payload.get("data", {}).get("children", []):
        d = child.get("data", {})
        if d.get("stickied") or d.get("over_18") or not d.get("title"):
            continue
        discussion = "https://www.reddit.com" + d.get("permalink", "")
        url = d.get("url_overridden_by_dest") or d.get("url") or discussion
        if d.get("is_self"):
            url = discussion
        image = None
        try:
            image = d["preview"]["images"][0]["source"]["url"]
        except (KeyError, IndexError, TypeError):
            pass
        if not image and IMAGE_EXT_RX.search(url or ""):
            image = url
        if not image and str(d.get("thumbnail", "")).startswith("http"):
            image = d["thumbnail"]
        summary = (d.get("selftext") or "").strip()
        items.append({
            "external_id": f"reddit:{d.get('id')}",
            "category": category,
            "title": html.unescape(d["title"]).strip(),
            "summary": summary[:4000] or None,
            "image_url": html.unescape(image) if image else None,
            "source_url": url,
            "discussion_url": discussion,
            "source": f"r/{d.get('subreddit') or sub}",
            "comments_count": int(d.get("num_comments") or 0),
            "score": int(d.get("score") or 0),
            "created_at": int(d.get("created_utc") or time.time()),
        })
    return items


async def fetch_reddit(client: httpx.AsyncClient) -> list[Item]:
    items: list[Item] = []
    for category, subs in config.REDDIT_SUBS.items():
        for sub in subs:
            for host in ("www.reddit.com", "old.reddit.com"):
                url = f"https://{host}/r/{sub}/top.json?t=day&limit=50&raw_json=1"
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    items += parse_reddit(r.json(), category, sub)
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning("Reddit r/%s via %s: %s", sub, host, e)
            await asyncio.sleep(1)  # вежливость к неавторизованному API
    return items


def parse_hn(payload: dict) -> list[Item]:
    items = []
    for hit in payload.get("hits", []):
        title = hit.get("title") or ""
        category = classify(title)
        if not category:
            continue
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        items.append({
            "external_id": f"hn:{hit['objectID']}",
            "category": category,
            "title": title.strip(),
            "summary": (hit.get("story_text") or None),
            "image_url": None,
            "source_url": hit.get("url") or discussion,
            "discussion_url": discussion,
            "source": "Hacker News",
            "comments_count": int(hit.get("num_comments") or 0),
            "score": int(hit.get("points") or 0),
            "created_at": int(hit.get("created_at_i") or time.time()),
        })
    return items


async def fetch_hn(client: httpx.AsyncClient) -> list[Item]:
    since = int(time.time() - config.WINDOW_HOURS * 3600)
    min_points = min(config.MIN_SCORE, 50)
    url = (
        "https://hn.algolia.com/api/v1/search"
        f"?tags=story&hitsPerPage=500&numericFilters=created_at_i>{since},points>{min_points}"
    )
    r = await client.get(url)
    r.raise_for_status()
    return parse_hn(r.json())


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_rss(content: bytes, category: str, name: str) -> list[Item]:
    feed = feedparser.parse(content)
    items = []
    for e in feed.entries:
        link = e.get("link")
        if not link or not e.get("title"):
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        created = calendar.timegm(ts) if ts else int(time.time())
        image = None
        for key in ("media_content", "media_thumbnail"):
            media = e.get(key)
            if media and media[0].get("url"):
                image = media[0]["url"]
                break
        if not image:
            for enc in e.get("enclosures", []):
                if str(enc.get("type", "")).startswith("image"):
                    image = enc.get("href")
                    break
        items.append({
            "external_id": f"rss:{link}",
            "category": category,
            "title": _strip_html(e.title),
            "summary": _strip_html(e.get("summary", ""))[:1000] or None,
            "image_url": image,
            "source_url": link,
            "discussion_url": None,
            "source": name,
            "comments_count": 0,
            "score": 0,
            "created_at": int(created),
        })
    return items


async def fetch_rss(client: httpx.AsyncClient) -> list[Item]:
    async def one(category: str, name: str, url: str) -> list[Item]:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return parse_rss(r.content, category, name)
        except Exception as e:  # noqa: BLE001
            log.warning("RSS %s: %s", name, e)
            return []

    jobs = [one(c, n, u) for c, feeds in config.RSS_FEEDS.items() for n, u in feeds]
    return [i for chunk in await asyncio.gather(*jobs) for i in chunk]


def parse_hf(payload: list) -> list[Item]:
    items = []
    for m in payload:
        model_id = m.get("id") or m.get("modelId")
        likes = int(m.get("likes") or 0)
        if not model_id or likes < config.HF_MIN_LIKES:
            continue
        created = m.get("createdAt") or ""
        try:
            created_ts = calendar.timegm(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            created_ts = int(time.time())
        url = f"https://huggingface.co/{model_id}"
        items.append({
            "external_id": f"hf:{model_id}",
            "category": "ai",
            "title": f"В тренде Hugging Face: {model_id}",
            "summary": f"Модель {model_id} — {m.get('pipeline_tag') or 'модель'}, "
                       f"{likes} лайков, {m.get('downloads', 0)} загрузок.",
            "image_url": None,
            "source_url": url,
            "discussion_url": url + "/discussions",
            "source": "Hugging Face",
            "comments_count": 0,
            "score": likes,
            "created_at": created_ts,
        })
    return items


async def fetch_hf(client: httpx.AsyncClient) -> list[Item]:
    r = await client.get("https://huggingface.co/api/models?sort=trendingScore&limit=15")
    r.raise_for_status()
    return parse_hf(r.json())


# --------------------------------------------------------------------------- #
# Превью-картинки
# --------------------------------------------------------------------------- #
OG_RX = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)(?::src)?["'][^>]*>""", re.I
)
CONTENT_RX = re.compile(r"""content=["']([^"']+)["']""", re.I)


def extract_og_image(page: str) -> str | None:
    m = OG_RX.search(page)
    if m:
        c = CONTENT_RX.search(m.group(0))
        if c:
            return html.unescape(c.group(1))
    return None


async def enrich_images(client: httpx.AsyncClient, items: list[Item]) -> None:
    sem = asyncio.Semaphore(6)

    async def one(item: Item):
        url = item.get("source_url")
        if item.get("image_url") or not url or url == item.get("discussion_url"):
            return
        async with sem:
            try:
                r = await client.get(url, timeout=8)
                if "html" in r.headers.get("content-type", ""):
                    item["image_url"] = extract_og_image(r.text[:300_000])
            except Exception as e:  # noqa: BLE001
                log.debug("og:image %s: %s", url, e)

    await asyncio.gather(*(one(i) for i in items))


# --------------------------------------------------------------------------- #
# Прогон
# --------------------------------------------------------------------------- #
_lock = asyncio.Lock()


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
    )


async def gather_sources(client: httpx.AsyncClient) -> tuple[list[Item], list[Item], list[str]]:
    sources = {"reddit": fetch_reddit(client), "hn": fetch_hn(client), "rss": fetch_rss(client)}
    if config.HF_TRENDING_ENABLED:
        sources["hf"] = fetch_hf(client)
    results = await asyncio.gather(*sources.values(), return_exceptions=True)
    hot, rss, errors = [], [], []
    for name, res in zip(sources, results):
        if isinstance(res, Exception):
            log.warning("Источник %s недоступен: %s", name, res)
            errors.append(name)
        elif name == "rss":
            rss = res
        else:
            hot += res
    if not rss and "rss" not in errors and config.RSS_FEEDS:
        errors.append("rss")
    return hot, rss, errors


def build_selection(fresh_hot: list[Item], rss: list[Item], existing: list[dict]) -> list[Item]:
    cutoff = time.time() - config.WINDOW_HOURS * 3600
    by_id: dict[str, Item] = {}
    # Записи из БД — запасной вариант, свежие данные их перекрывают.
    for row in existing:
        if row["created_at"] >= cutoff and not row["external_id"].startswith("rss:"):
            by_id[row["external_id"]] = {f: row.get(f) for f in db.FIELDS}
    for item in fresh_hot:
        if item["created_at"] >= cutoff:
            by_id[item["external_id"]] = item
    hot = deduplicate([i for i in by_id.values() if passes_threshold(i)])
    fresh_rss = [i for i in rss if i["created_at"] >= cutoff]
    return select_top(hot, deduplicate(fresh_rss))


async def refresh() -> dict:
    """Полный цикл обновления. Безопасен для параллельного вызова."""
    async with _lock:
        started = time.time()
        async with make_client() as client:
            hot, rss, errors = await gather_sources(client)
            if not hot and not rss:
                log.error("Ни один источник не ответил — лента не изменена")
                return {"ok": False, "items": len(db.list_news()), "errors": errors}
            selection = build_selection(hot, rss, db.all_rows())
            await enrich_images(client, selection)
        db.replace_selection(selection)
        stats = {
            "ok": True,
            "items": len(selection),
            "candidates": len(hot) + len(rss),
            "errors": errors,
            "seconds": round(time.time() - started, 1),
        }
        log.info("Лента обновлена: %s", stats)
        return stats


def is_running() -> bool:
    return _lock.locked()
