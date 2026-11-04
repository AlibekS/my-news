import time

import pytest

from mynews import collector, config, db, reader

NOW = int(time.time())


def item(eid, title, cat="hardware", comments=0, score=0, url=None, age_h=1, **kw):
    d = {
        "external_id": eid, "category": cat, "title": title, "summary": None, "image_url": None,
        "source_url": url or f"https://www.reddit.com/r/x/{eid}", "discussion_url": f"https://www.reddit.com/r/x/{eid}",
        "source": "r/x", "comments_count": comments, "score": score, "created_at": NOW - age_h * 3600,
    }
    d.update(kw)
    return d


def test_threshold():
    assert collector.passes_threshold(item("a", "t", comments=101))
    assert collector.passes_threshold(item("b", "t", score=251))
    assert not collector.passes_threshold(item("c", "t", comments=100, score=250))


@pytest.mark.parametrize("title,cat", [
    ("Nvidia announces RTX 5090 Ti with 32GB GDDR7", "hardware"),
    ("OpenAI releases new reasoning model", "ai"),
    ("Valve's Steam hits record concurrent users", "games"),
    ("Show HN: My weekend woodworking project", None),
    ("Running LLMs locally on a Mac", "ai"),
    ("Benchmarking AMD GPUs for gaming", "hardware"),
])
def test_classify(title, cat):
    assert collector.classify(title) == cat


def test_dedup_keeps_most_discussed_and_merges_image():
    a = item("reddit:1", "Nvidia announces RTX 5090 with 32GB of GDDR7 memory", comments=300,
             url="https://videocardz.com/rtx-5090")
    b = item("hn:2", "NVIDIA announces the RTX 5090: 32GB GDDR7 memory", comments=500,
             url="https://www.nvidia.com/news/rtx5090", source="Hacker News")
    c = item("rss:3", "Something different entirely about Intel fabs", comments=200,
             image_url="https://img/x.jpg")
    d = item("reddit:4", "RTX 5090 review roundup", comments=150, url="https://videocardz.com/rtx-5090/",
             image_url="https://img/5090.jpg")
    out = collector.deduplicate([a, b, c, d])
    ids = [i["external_id"] for i in out]
    assert ids == ["hn:2", "rss:3"]
    assert out[0]["image_url"] == "https://img/5090.jpg"  # картинка взята у дубля


def test_dedup_same_url():
    a = item("reddit:1", "Totally different words here", comments=150, url="https://site.com/a?utm=1")
    b = item("hn:1", "Unrelated headline text", comments=250, url="https://www.site.com/a/")
    out = collector.deduplicate([a, b])
    assert [i["external_id"] for i in out] == ["hn:1"]


def test_select_top_limit_and_rss_fallback(monkeypatch):
    monkeypatch.setattr(config, "PER_CATEGORY_LIMIT", 3)
    monkeypatch.setattr(config, "RSS_FALLBACK_MIN", 2)
    hot = [item(f"h{i}", f"unique hardware story number {i} words", comments=100 + i) for i in range(5)]
    rss = [item("r1", "AI feed headline about models", cat="ai", age_h=2),
           item("r2", "AI feed second headline about chips", cat="ai", age_h=1),
           item("r3", "AI feed third headline about training", cat="ai", age_h=3)]
    out = collector.select_top(hot, rss)
    hw = [i for i in out if i["category"] == "hardware"]
    assert [i["external_id"] for i in hw] == ["h4", "h3", "h2"]
    assert [i["external_id"] for i in out if i["category"] == "ai"] == ["r2", "r1"]


def test_parse_reddit():
    payload = {"data": {"children": [
        {"data": {"id": "x1", "title": "Big &amp; news", "permalink": "/r/hardware/comments/x1/",
                  "url": "https://example.com/a", "num_comments": 420, "score": 1200,
                  "created_utc": NOW, "subreddit": "hardware",
                  "preview": {"images": [{"source": {"url": "https://preview.redd.it/a.jpg?w=1&amp;s=2"}}]}}},
        {"data": {"id": "x2", "title": "Pinned", "stickied": True, "permalink": "/x"}},
        {"data": {"id": "x3", "title": "Self post", "is_self": True, "selftext": "body",
                  "permalink": "/r/hardware/comments/x3/", "url": "https://www.reddit.com/r/hardware/comments/x3/",
                  "num_comments": 5, "score": 3, "created_utc": NOW}},
    ]}}
    out = collector.parse_reddit(payload, "hardware", "hardware")
    assert len(out) == 2
    assert out[0]["title"] == "Big & news"
    assert out[0]["image_url"] == "https://preview.redd.it/a.jpg?w=1&s=2"
    assert out[1]["source_url"] == out[1]["discussion_url"]


def test_summarize():
    text = (
        "Nvidia has announced the RTX 5090 graphics card at CES. "
        "The RTX 5090 graphics card features 32GB of GDDR7 memory and a new architecture. "
        "Pricing starts at $1999 for the RTX 5090. "
        "Weather in Las Vegas was pleasant during the show this year. "
        "Nvidia says the graphics card doubles performance in ray tracing workloads. "
        "Availability is expected in late January for the RTX 5090 graphics card. "
        "Some attendees enjoyed the food courts very much indeed."
    )
    out = reader.summarize(text, "Nvidia announces RTX 5090", n=3)
    assert len(out) == 3
    assert all("Weather" not in s for s in out)


def test_build_selection_and_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "news.db")
    db.init()
    fresh = [item("reddit:a", "Hot hardware topic about GPUs today", comments=500),
             item("reddit:b", "Quiet post nobody cares about", comments=3, score=10),
             item("reddit:old", "Old hardware topic from two days ago", comments=900, age_h=48)]
    sel = collector.build_selection(fresh, [], [])
    assert [i["external_id"] for i in sel] == ["reddit:a"]
    db.replace_selection(sel)
    nid = db.list_news()[0]["id"]
    db.save_article(nid, "text", ["point"], None)
    # Следующий прогон: источник временно молчит — запись сохраняется, кэш тоже
    sel2 = collector.build_selection([], [], db.all_rows())
    db.replace_selection(sel2)
    row = db.get(nid)
    assert row and row["tldr"] == '["point"]'
