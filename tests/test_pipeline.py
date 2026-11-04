import time

import pytest

from mynews import collector, config, db, reader

NOW = int(time.time())


def item(url, title, topics=("ai",), lang=None, age_h=1, **kw):
    d = {
        "external_id": collector.canonical_url(url), "topics": list(topics), "title": title,
        "summary": None, "image_url": None, "source_url": url, "discussion_url": None,
        "source": kw.pop("source", collector.canonical_url(url).split("/")[0]),
        "lang": lang or collector.detect_lang(title), "region": kw.pop("region", "ru"), "comments_count": 0, "score": 0, "weight": 0.0,
        "also": [], "created_at": NOW - int(age_h * 3600),
    }
    d.update(kw)
    return d


@pytest.mark.parametrize("title,expected", [
    ("OpenAI представила новую нейросеть для генерации видео", "ai"),
    ("В России запустили ИИ-ассистента для врачей", "ai"),
    ("Nvidia анонсировала GeForce RTX 5090 Super", "hardware"),
    ("Вышел первый трейлер новой игры от CD Projekt", "games"),
    ("Valve's Steam hits record concurrent users", "games"),
    ("SpaceX провела очередной запуск Starship", "space"),
])
def test_classify(title, expected):
    assert expected in collector.classify(title)


def test_classify_no_false_positives():
    assert collector.classify("Business intelligence report for retail") == []
    assert collector.classify("На линии метро открыли новые станции") == []


def test_primary_topic_by_match_strength():
    t = collector.classify("«Битва моторов» собрала миллиард рублей в российском прокате", "",
                           {"topic": "games", "mode": "fallback"})
    assert t[0] == "movies"
    t = collector.classify("Обычный смартфон смог переключиться с наземной вышки на спутник", "",
                           {"topic": "hardware", "mode": "bound"})
    # «смартфон» и «спутник» весят одинаково; главное — тема ленты («Железо») уже не первая
    assert t[0] in ("gadgets", "space") and t[-1] == "hardware"


def test_sections_use_best_topic_not_page_order():
    pool = [dict(item("https://a.ru/1", "Фильм собрал рекорд", topics=["movies", "economy"]), id=1)]
    secs = collector.build_sections(pool, ["economy", "movies"], [], None)
    assert {s["topic"]: [i["id"] for i in s["items"]] for s in secs} == {"economy": [], "movies": [1]}


def test_feed_modes():
    bound = {"topic": "games", "mode": "bound"}
    fallback = {"topic": "games", "mode": "fallback"}
    assert collector.classify("Обзор недели", feed=bound) == ["games"]
    assert collector.classify("Обзор недели", feed=fallback) == ["games"]
    assert collector.classify("Netflix продлил сериал на второй сезон", feed=fallback) == ["movies"]


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>T</title>
<item><title>AMD &amp; Intel: \xd0\xbd\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb5 \xd0\xbf\xd1\x80\xd0\xbe\xd1\x86\xd0\xb5\xd1\x81\xd1\x81\xd0\xbe\xd1\x80\xd1\x8b</title>
<link>https://www.example.ru/news/1/?utm_source=rss</link>
<description>&lt;p&gt;&lt;img src="https://img.example.ru/1.jpg"&gt;Text here&lt;/p&gt;</description>
<pubDate>Tue, 04 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title></title><link>https://example.ru/2</link></item>
</channel></rss>"""


def test_parse_feed():
    out = collector.parse_feed(RSS, {"name": "Пример", "topic": "hardware", "mode": "bound"})
    assert len(out) == 1
    it = out[0]
    assert it["external_id"] == "example.ru/news/1"
    assert it["image_url"] == "https://img.example.ru/1.jpg"
    assert it["lang"] == "ru" and it["topics"][0] == "hardware"
    assert it["summary"] == "Text here"


def test_dedup_prefers_russian_and_collects_sources():
    en = item("https://videocardz.com/a", "Nvidia GeForce RTX 5090 Super launches with 32GB memory",
              topics=["hardware"], comments_count=400, discussion_url="https://news.ycombinator.com/item?id=1",
              source="Hacker News")
    ru1 = item("https://3dnews.ru/1", "Nvidia представила GeForce RTX 5090 Super с 32 ГБ памяти",
               topics=["hardware"], image_url="https://3dnews.ru/i.jpg", source="3DNews")
    ru2 = item("https://ixbt.com/2", "Nvidia представила видеокарту GeForce RTX 5090 Super с 32 ГБ",
               topics=["hardware"], source="iXBT")
    same_url = item("https://www.3dnews.ru/1/", "Совсем другой заголовок про это же", topics=["hardware"], source="3DNews RSS")
    other = item("https://x.ru/3", "Intel снизила цены на процессоры Core Ultra", topics=["hardware"])
    out = collector.deduplicate([en, ru1, ru2, same_url, other])
    assert len(out) == 2
    win = next(o for o in out if "RTX" in o["title"])
    assert win["lang"] == "ru" and win["source"] == "3DNews"
    assert {a["source"] for a in win["also"]} == {"iXBT", "Hacker News"}
    # обсуждение и счётчик комментариев берутся у англоязычного дубля с HN
    assert win["discussion_url"].startswith("https://news.ycombinator.com") and win["comments_count"] == 400

@pytest.mark.parametrize("a,b,dup", [
    ("OpenAI представила GPT-5.5 с режимом долгих рассуждений",
     "OpenAI представила GPT-5.5: модель научилась долгим рассуждениям", True),
    ("Nvidia представила GeForce RTX 5090", "Nvidia представила GeForce RTX 5080", False),
    ("Steam установил новый рекорд по одновременному онлайну",
     "Steam побил рекорд одновременного онлайна пользователей", True),
    ("Apple выпустила iOS 26.1 с исправлениями", "Apple выпустила новые MacBook Pro", False),
    ("Intel снизила цены на процессоры Core Ultra", "AMD снизила цены на процессоры Ryzen", False),
])
def test_is_duplicate(a, b, dup):
    assert collector.is_duplicate(item("https://x.ru/1", a), item("https://y.ru/2", b)) is dup


def test_dedup_is_order_independent():
    x = item("https://ixbt.com/1", "OpenAI выпустила GPT-5.5 с новым режимом рассуждений", age_h=4)
    b = item("https://3dnews.ru/1", "OpenAI представила GPT-5.5: модель научилась долгим рассуждениям", age_h=3)
    a = item("https://habr.com/1", "OpenAI представила GPT-5.5 с режимом долгих рассуждений", age_h=2)
    out = collector.deduplicate([x, b, a])
    assert len(out) == 1 and len(out[0]["also"]) == 2


def test_hotness_prefers_coverage_and_freshness():
    a = item("https://a.ru/1", "Один", age_h=1)
    b = item("https://b.ru/1", "Два", age_h=1, also=[{"source": "x", "url": "u"}, {"source": "y", "url": "v"}])
    c = item("https://c.ru/1", "Три", age_h=30)
    assert collector.hotness(b) > collector.hotness(a) > collector.hotness(c)


def test_build_sections():
    pool = [
        dict(item("https://a.ru/1", "Нейросеть рисует видеокарты", topics=["ai", "hardware"]), id=1),
        dict(item("https://a.ru/2", "Новая видеокарта Radeon", topics=["hardware"]), id=2),
        dict(item("https://a.com/3", "New GPU from AMD", topics=["hardware"], region="en"), id=3),
        dict(item("https://a.ru/4", "Apple показала новый iPhone", topics=["gadgets"]), id=4),
    ]
    secs = collector.build_sections(pool, ["ai", "hardware", "c-1"], [{"id": "c-1", "keywords": "iphone, макбук"}], None)
    ids = {s["topic"]: [i["id"] for i in s["items"]] for s in secs}
    assert ids["ai"] == [1]
    assert 1 not in ids["hardware"] and set(ids["hardware"]) == {2, 3}
    assert ids["c-1"] == [4]
    ru = collector.build_sections(pool, ["hardware"], [], "ru")
    assert {i["id"] for i in ru[0]["items"]} == {1, 2}
    en = collector.build_sections(pool, ["hardware"], [], "en")
    assert [i["id"] for i in en[0]["items"]] == [3]


def test_kz_region_only_russian_language():
    pool = [
        dict(item("https://tengrinews.kz/1", "Нацбанк Казахстана сохранил базовую ставку", topics=["economy"], region="kz"), id=1),
        dict(item("https://kapital.kz/2", "Tenge exchange rate falls", topics=["economy"], region="kz"), id=2),
        dict(item("https://rbc.ru/3", "ЦБ России снизил ключевую ставку", topics=["economy"]), id=3),
    ]
    kz = collector.build_sections(pool, ["economy"], [], "kz")
    assert [i["id"] for i in kz[0]["items"]] == [1]


def test_merge_pool_dedups_within_region_only():
    ru = item("https://rbc.ru/1", "Токаев подписал закон о цифровом тенге и криптовалютах", topics=["economy"])
    kz = item("https://tengrinews.kz/1", "Токаев подписал закон о цифровом тенге и криптовалютах", topics=["economy"], region="kz")
    out = collector.merge_pool([ru, kz], [])
    assert {o["region"] for o in out} == {"ru", "kz"}


def test_summarize_russian():
    text = (
        "Компания Nvidia представила видеокарту GeForce RTX 5090 Super на выставке CES. "
        "Новая видеокарта получила 32 ГБ памяти GDDR7 и обновлённую архитектуру. "
        "Погода в Лас-Вегасе во время выставки была солнечной и тёплой. "
        "Стоимость видеокарты Nvidia составит 1999 долларов в США. "
        "Продажи видеокарты начнутся в конце января во всех регионах. "
        "Посетители выставки также отметили вкусную еду на фудкортах."
    )
    out = reader.summarize(text, "Nvidia представила GeForce RTX 5090 Super", n=3)
    assert len(out) == 3 and not any("Погода" in s for s in out)


def test_db_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "news.db")
    db.init()
    a = item("https://a.ru/1", "Нейросеть", image_url="https://i/1.jpg")
    db.replace_pool([a])
    row = db.pool(0)[0]
    db.save_article(row["id"], "text", ["point"], None)
    # повторный прогон: картинки в ленте нет — сохраняется найденная ранее; кэш TL;DR цел
    b = dict(a, image_url=None, title="Нейросеть v2")
    db.replace_pool([b, item("https://a.ru/2", "Другая")])
    got = db.get(row["id"])
    assert got["title"] == "Нейросеть v2" and got["image_url"] == "https://i/1.jpg" and got["tldr"] == '["point"]'
    db.replace_pool([item("https://a.ru/2", "Другая")])
    assert db.get(row["id"]) is None


def test_merge_pool_keeps_items_from_failed_feeds(tmp_path, monkeypatch):
    old = item("https://a.ru/old", "Старая новость из упавшей ленты про нейросети")
    stale = item("https://a.ru/stale", "Совсем старая", age_h=100)
    fresh = item("https://b.ru/new", "Свежая новость про видеокарты", topics=["hardware"])
    out = collector.merge_pool([fresh], [old, stale])
    assert {o["external_id"] for o in out} == {"a.ru/old", "b.ru/new"}


def test_discover_feed_url():
    page = '''<html><head>
      <link rel="alternate" type="application/rss+xml" title="Комментарии" href="/comments/feed/">
      <link rel="alternate" type="application/rss+xml" title="Новости" href="/feed/">
    </head></html>'''
    assert collector.discover_feed_url(page, "https://example.kz/") == "https://example.kz/feed/"


def test_fetch_feed_tries_alternatives_and_discovers(monkeypatch):
    import asyncio

    import httpx

    def handler(request: httpx.Request):
        url = str(request.url)
        if url == "https://site.kz/rss":
            return httpx.Response(404)
        if url == "https://site.kz/":
            return httpx.Response(200, text='<!doctype html><html><head><link rel="alternate" '
                                  'type="application/rss+xml" href="https://site.kz/news.xml"></head></html>',
                                  headers={"content-type": "text/html"})
        if url == "https://site.kz/news.xml":
            return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})
        return httpx.Response(500)

    feed = {"name": "Site", "urls": ["https://site.kz/rss", "https://site.kz/"], "mode": "classify",
            "region": "kz", "topic": None, "weight": 0}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collector.fetch_feed(client, feed, asyncio.Semaphore(1))

    items, status = asyncio.run(run())
    assert status["ok"] and status["url"] == "https://site.kz/news.xml"
    assert items and items[0]["region"] == "kz"


def test_hidden_sources_fall_back_to_other_outlet():
    a = dict(item("https://dtf.ru/1", "Новость про игры", topics=["games"], source="DTF",
                  also=[{"source": "StopGame", "url": "https://stopgame.ru/1"}]), id=1)
    b = dict(item("https://dtf.ru/2", "Другая новость", topics=["games"], source="DTF"), id=2)
    c = dict(item("https://pg.ru/3", "Третья", topics=["games"], source="PlayGround",
                  also=[{"source": "DTF", "url": "https://dtf.ru/3"}]), id=3)
    secs = collector.build_sections([a, b, c], ["games"], [], None, hidden_sources={"DTF"})
    got = {i["id"]: i for i in secs[0]["items"]}
    assert set(got) == {1, 3}
    assert got[1]["source"] == "StopGame" and got[1]["source_url"] == "https://stopgame.ru/1"
    assert got[3]["also"] == []


def test_summary_keeps_context_for_anaphora():
    text = (
        "Министр финансов Мади Такиев выступил в мажилисе с докладом о бюджете. "
        "По его словам, на внешнем рынке Казахстан планирует привлечь 3,5 млрд долларов и 1,6 трлн тенге. "
        "Дефицит бюджета Казахстана на 2026 год составляет 4,6 трлн тенге по данным министерства. "
        "Дефицит бюджета Казахстана на следующий год составит около 4,6 трлн тенге. "
        "Погода в Астане в этот день была солнечной и безветренной для ноября. "
        "Часть средств планируют привлечь у международных финансовых организаций."
    )
    out = reader.summarize(text, "Как Казахстан планирует покрыть дефицит бюджета в 4,6 трлн тенге", n=4)
    for i, s in enumerate(out):
        if s.startswith("По его словам"):
            assert i > 0 and "Такиев" in out[i - 1]   # есть, о ком речь
    assert sum("Дефицит бюджета" in s for s in out) <= 1  # без повторов


DDG_HTML = """
<div class="result results_links results_links_deep result--ad"><h2 class="result__title">
<a class="result__a" href="https://ad.example/">Реклама</a></h2></div>
<div class="result results_links results_links_deep web-result "><div class="links_main">
<h2 class="result__title"><a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Frozetked.me%2Farticles%2F123-obzor-iphone&amp;rut=abc">Обзор <b>iPhone 18 Pro</b> — Rozetked</a></h2>
<a class="result__snippet" href="x">Подробный <b>обзор</b> нового смартфона.</a></div></div>
<div class="result results_links web-result "><h2 class="result__title">
<a class="result__a" href="https://www.ixbt.com/mobile/iphone-18-pro-review.html">iPhone 18 Pro: тест</a></h2>
<a class="result__snippet" href="y">Тестируем камеру.</a></div>
"""


def test_parse_ddg():
    from mynews import search
    out = search.parse_ddg(DDG_HTML)
    assert [r["url"] for r in out] == ["https://rozetked.me/articles/123-obzor-iphone",
                                       "https://www.ixbt.com/mobile/iphone-18-pro-review.html"]
    assert out[0]["title"] == "Обзор iPhone 18 Pro — Rozetked" and out[0]["snippet"] == "Подробный обзор нового смартфона."


def test_parse_bing_and_rank():
    from mynews import search
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Bing</title>
    <item><title>iPhone 18 Pro review</title><link>https://www.theverge.com/iphone-18</link><description>English</description></item>
    <item><title>\xd0\x9e\xd0\xb1\xd0\xb7\xd0\xbe\xd1\x80 iPhone 18 Pro</title><link>https://rozetked.me/articles/123-obzor-iphone/</link><description>x</description></item>
    </channel></rss>"""
    bing = search.parse_bing_rss(rss)
    merged = search.rank(search.parse_ddg(DDG_HTML) + bing)
    urls = [r["url"] for r in merged]
    assert urls.count("https://rozetked.me/articles/123-obzor-iphone") == 1     # дубль убран
    assert merged[-1]["lang"] == "en" and merged[0]["source"] == "rozetked.me"  # русские выше


def test_read_url_blocks_local_addresses():
    import pytest as _p
    from mynews import search
    for bad in ["http://127.0.0.1:8000/", "file:///etc/passwd", "http://192.168.1.1/admin", "ftp://x"]:
        with _p.raises(search.BadURL):
            search.check_url(bad)


def test_article_images_kept_and_cleaned():
    raw = "\n".join([
        "Первый абзац обзора видеокарты.",
        "![Видеокарта сбоку](https://cdn.example.com/gpu.jpg?w=800)",
        "![](https://cdn.example.com/gpu.jpg?w=1200)",          # повтор той же картинки
        "![](https://example.com/static/logo.png)",             # логотип
        "![](https://mc.yandex.ru/watch/123)",                  # счётчик
        "![обложка](https://cdn.example.com/hero.jpg)",         # совпадает с обложкой
        "![битая](https://cdn.exa",                             # обрезанная разметка
        "Второй абзац с тестами в играх.",
    ])
    out = reader.clean_content(raw, hero="https://cdn.example.com/hero.jpg")
    assert out.split("\n") == [
        "Первый абзац обзора видеокарты.",
        "![Видеокарта сбоку](https://cdn.example.com/gpu.jpg?w=800)",
        "Второй абзац с тестами в играх.",
    ]
    # картинки не попадают в краткое содержание и не считаются текстом
    assert reader.text_only(out) == "Первый абзац обзора видеокарты.\nВторой абзац с тестами в играх."
    assert all("![" not in s for s in reader.split_sentences(out))


def test_article_text_limit_ignores_images():
    raw = "\n".join(["а" * 50, "![x](https://cdn.example.com/1.jpg)", "б" * 50, "![y](https://cdn.example.com/2.jpg)"])
    out = reader.clean_content(raw, limit=80)
    assert out.split("\n") == ["а" * 50, "![x](https://cdn.example.com/1.jpg)", "б" * 30]


def test_extract_text_includes_images():
    para = "Абзац о новой видеокарте и её производительности в современных играх. " * 6
    html = (f"<html><body><article><h1>Обзор</h1><p>{para}</p>"
            f"<figure><img src='/img/gpu.jpg' alt='Плата'></figure><p>{para}</p></article></body></html>")
    out = reader.clean_content(reader.extract_text(html, "https://example.com/news/1"))
    assert "![Плата](https://example.com/img/gpu.jpg)" in out.split("\n")
