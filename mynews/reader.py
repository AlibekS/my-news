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


# Картинки внутри текста статьи хранятся отдельной строкой в виде «![подпись](https://…)».
IMG_LINE_RX = re.compile(r"^!\[([^\]\n]{0,300})\]\((https?://[^\s)]+)\)$")
# Счётчики, пиксели, логотипы, аватарки, иконки соцсетей — это не иллюстрации статьи.
JUNK_IMG_RX = re.compile(
    r"\.svg(?:$|\?)|(?:pixel|spacer|blank|1x1)\.(?:gif|png)|(?<![a-z])(?:logo|avatar|userpic|icon|favicon|emoji|"
    r"sprite)s?(?![a-z])|gravatar\.com|doubleclick\.net|mc\.yandex|counter\.yadro|top-fwz|facebook\.com/tr",
    re.I,
)
MAX_IMAGES = 12


def is_image_line(line: str) -> bool:
    return bool(IMG_LINE_RX.match(line.strip()))


def text_only(content: str) -> str:
    """Текст статьи без строк-картинок — для краткого содержания и подсчёта длины."""
    return "\n".join(line for line in content.split("\n") if not is_image_line(line))


def clean_content(raw: str, hero: str | None = None, limit: int = MAX_CONTENT_CHARS) -> str:
    """Приводит вывод trafilatura к виду «абзацы + строки-картинки».

    Оставляет только http(s)-картинки, убирает мусор (пиксели, логотипы), повторы и
    картинку, совпадающую с обложкой (она и так показана сверху). Лимит длины
    считается по тексту — картинки его не съедают.
    """
    out: list[str] = []
    seen: set[str] = {hero.split("?")[0]} if hero else set()
    images = chars = 0
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("!["):
            m = IMG_LINE_RX.match(line)
            if not m:
                continue  # битая/неполная разметка картинки — пропускаем
            alt, src = m.group(1).strip(), m.group(2)
            key = src.split("?")[0]
            if key in seen or JUNK_IMG_RX.search(src) or images >= MAX_IMAGES:
                continue
            seen.add(key)
            images += 1
            out.append(f"![{alt}]({src})")
            continue
        if chars >= limit:
            break
        line = line[: limit - chars]
        chars += len(line)
        out.append(line)
    while out and is_image_line(out[-1]) and chars >= limit:
        out.pop()  # картинки после обрезанного текста не нужны
    return "\n".join(out)


def split_sentences(text: str) -> list[str]:
    sentences = []
    for para in re.split(r"\n+", text):
        para = para.strip()
        if para and not is_image_line(para):
            sentences += [s.strip() for s in SENT_SPLIT_RX.split(para) if s.strip()]
    return sentences


# Предложения, которые без предыдущего непонятны: «По его словам…», «Он отметил…», «Это…».
ANAPHORA_RX = re.compile(
    r"^[\"«(]*(?:по\s+(?:его|её|ее|их)\s+(?:словам|мнению|данным|оценке)|"
    r"он|она|оно|они|его|её|ее|их|ему|ей|им|это|эти|этот|эта|этого|этой|этим|такой|такая|такие|таким|"
    r"также|тоже|при\s+этом|кроме\s+того|помимо\s+этого|однако|но|а|и|поэтому|тем\s+не\s+менее|"
    r"в\s+свою\s+очередь|впрочем|из\s+(?:этой|этого|этих|них)|в\s+том\s+числе|then|he|she|it|they|this|these|that|those|however|also|but|and|so)\b",
    re.I,
)


def needs_context(sentence: str) -> bool:
    return bool(ANAPHORA_RX.match(sentence.strip()))


def summarize(text: str, title: str = "", n: int = 4) -> list[str]:
    """Экстрактивное краткое содержание: до n ключевых предложений в исходном порядке.

    - предложение со ссылкой на предыдущее («По его словам…») берётся только вместе
      с предыдущим, иначе пропускается — чтобы не было «чьим словам?»;
    - почти повторяющие друг друга предложения не берутся дважды.
    """
    sentences = split_sentences(text)
    ok = [40 <= len(s) <= 400 and not s.endswith(":") and not s.lower().startswith(("image", "photo", "credit", "фото"))
          for s in sentences]
    candidates = [(i, s) for i, s in enumerate(sentences) if ok[i]]
    if not candidates:
        return sentences[:n]

    def words(s: str) -> list[str]:
        # грубый стемминг (первые 6 букв), чтобы «видеокарта/видеокарту» считались одним словом
        return [w.lower().replace("ё", "е")[:6] for w in WORD_RX.findall(s) if w.lower() not in STOP and len(w) > 2]

    freq = Counter(w for _, s in candidates for w in words(s))
    top = max(freq.values()) if freq else 1
    title_words = set(words(title))
    total = len(sentences)

    scores: dict[int, float] = {}
    for i, s in candidates:
        ws = words(s)
        if not ws:
            continue
        score = sum(freq[w] / top for w in ws) / math.sqrt(len(ws))
        score += 0.3 * len(title_words & set(ws))
        score *= 1.25 if i < max(3, total * 0.15) else 1.0  # лид статьи важнее
        if needs_context(s):
            score *= 0.6
        scores[i] = score

    chosen: list[int] = []
    chosen_words: list[set] = []

    def similar(ws: set) -> bool:
        return any(len(ws & c) / max(1, len(ws | c)) > 0.5 for c in chosen_words)

    def add(i: int) -> bool:
        ws = set(words(sentences[i]))
        if i in chosen or similar(ws):
            return False
        chosen.append(i)
        chosen_words.append(ws)
        return True

    for i in sorted(scores, key=lambda k: -scores[k]):
        if len(chosen) >= n:
            break
        if i in chosen:
            continue
        if needs_context(sentences[i]) and (i - 1) not in chosen:
            prev = i - 1
            # берём вместе с предыдущим предложением, если оно нормальное и есть место
            if prev >= 0 and ok[prev] and not needs_context(sentences[prev]) and len(chosen) + 2 <= n \
                    and not similar(set(words(sentences[prev]))):
                add(prev)
                add(i)
            continue
        add(i)
    return [sentences[i] for i in sorted(chosen)]


def extract_text(html_text: str, url: str) -> str:
    """Чистый текст статьи с картинками (строки «![подпись](url)»)."""
    return trafilatura.extract(
        html_text, url=url, include_comments=False, include_tables=False, include_images=True,
        favor_precision=True,
    ) or ""


def _extract(html_text: str, url: str) -> tuple[str, str | None]:
    text = extract_text(html_text, url)
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
    if item.get("content"):
        # Текст закэширован; краткое содержание пересчитываем (это быстро) —
        # так улучшения алгоритма сразу видны и на старых новостях.
        content = item["content"]
        return {"id": news_id, "tldr": summarize(text_only(content), item["title"]), "content": content,
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

    hero = item.get("image_url") or image
    text = clean_content(text, hero)
    if len(text_only(text)) < 200 and item.get("summary"):
        text = _clean_reddit_markdown(item["summary"])[:MAX_CONTENT_CHARS]

    tldr = summarize(text_only(text), item["title"]) if text else []
    if text:
        db.save_article(news_id, text, tldr, image)
    return {"id": news_id, "tldr": tldr, "content": text, "image_url": item.get("image_url") or image}
