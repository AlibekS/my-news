#!/usr/bin/env python3
"""«Обычный пользователь» для сайта «Волна».

Открывает сайт в настоящем браузере (Chromium через Playwright) и проходит типичный
сценарий: читает новости, жмёт кнопки, переключает темы и регионы, ищет, смотрит
мобильную версию. По пути снимает скриншоты, меряет время, ловит ошибки JavaScript,
упавшие запросы, «съехавшую» вёрстку и пустые места.

Результат — папка ux-report/<дата-время>/ с report.json и скриншотами. Дальше агент
Claude Code (.claude/agents/ux-reviewer.md) смотрит их и пишет человеческое ревью.

Запуск:
    python tools/ux_walkthrough.py                  # сценарий «утренний читатель»
    python tools/ux_walkthrough.py --persona gamer  # другой характер пользователя
    python tools/ux_walkthrough.py --refresh        # ещё и нажать «Обновить» (долго)
    python tools/ux_walkthrough.py --headed         # смотреть, как он кликает

Скрипт ничего не меняет в ваших настройках: у него свой «чистый» браузер.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import sys
import time
import traceback
from pathlib import Path

try:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Нужен Playwright:\n  pip install playwright\n  python -m playwright install chromium")

PERSONAS = {
    "morning": {
        "name": "Утренний читатель: 5 минут на главное за кофе",
        "queries": ["курс тенге", "новости ИИ сегодня", "обзор iPhone 18 Pro"],
        "reads": 3,
    },
    "gamer": {
        "name": "Геймер: релизы, железо, обзоры",
        "queries": ["GTA 6 дата выхода", "лучшая видеокарта для игр 2026", "обзор RTX 5080"],
        "reads": 4,
    },
    "investor": {
        "name": "Инвестор из Казахстана: экономика, KZ-новости",
        "queries": ["базовая ставка Нацбанк Казахстана", "курс тенге прогноз", "IPO Казахстан"],
        "reads": 3,
        "region": "kz",
    },
}

AUDIT_JS = r"""
() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  const imgs = [...document.images].filter(vis);
  const broken = imgs.filter(i => i.complete && i.naturalWidth === 0).map(i => i.src.slice(0, 120));
  const small = [...document.querySelectorAll('button, a, [role=button]')].filter(vis).filter(e => {
      const r = e.getBoundingClientRect(); return (r.width < 32 || r.height < 32) && !e.closest('.overlay.hidden');
    }).map(e => (e.getAttribute('aria-label') || e.textContent || e.className).trim().slice(0, 40));
  const clipped = [...document.querySelectorAll('.pill .nm, .card .title, .section-head h2')].filter(vis)
    .filter(e => e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).webkitLineClamp === 'none').map(e => e.textContent.trim().slice(0, 40));
  return {
    viewport: [innerWidth, innerHeight],
    horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1 ? document.documentElement.scrollWidth : 0,
    images_visible: imgs.length, images_broken: broken.slice(0, 10),
    small_tap_targets: [...new Set(small)].slice(0, 15),
    clipped_texts: clipped.slice(0, 10),
    cards: document.querySelectorAll('#feed .card').length,
    empty_sections: [...document.querySelectorAll('#feed .section')].filter(s => s.querySelector('.empty')).map(s => s.querySelector('h2')?.textContent),
    page_height: document.documentElement.scrollHeight,
  };
}
"""


class Walk:
    def __init__(self, out: Path, rnd: random.Random):
        self.out, self.rnd = out, rnd
        self.steps: list[dict] = []
        self.issues: list[dict] = []
        self.console: list[dict] = []
        self.failed: list[dict] = []
        self.n = 0
        self.page = None
        self.where = "desktop"

    # ---------- журнал ----------
    def attach(self, page, where: str):
        self.page, self.where = page, where
        page.on("console", lambda m: m.type in ("error", "warning") and self.console.append(
            {"where": where, "type": m.type, "text": m.text[:300]}))
        page.on("pageerror", lambda e: self.issue("bug", "Ошибка JavaScript на странице", str(e)[:400]))

        def on_response(r):
            if r.status >= 400 and "/api/" in r.url:
                self.failed.append({"where": where, "status": r.status, "url": r.url[:200]})
        page.on("response", on_response)
        page.on("requestfailed", lambda r: "/api/" in r.url and self.failed.append(
            {"where": where, "status": "failed", "url": r.url[:200], "error": (r.failure or "")[:120]}))

    def shot(self, name: str, full: bool = False) -> str:
        self.n += 1
        fname = f"{self.n:02d}-{self.where}-{name}.png"
        try:
            self.page.screenshot(path=str(self.out / fname), full_page=full)
        except Exception:  # noqa: BLE001
            return ""
        return fname

    def issue(self, severity: str, title: str, details: str = "", screenshot: str = ""):
        self.issues.append({"severity": severity, "where": self.where, "title": title,
                            "details": details, "screenshot": screenshot})

    def step(self, name: str, fn):
        t0 = time.perf_counter()
        rec = {"step": name, "where": self.where, "ok": True}
        try:
            rec["result"] = fn() or {}
        except Exception as e:  # noqa: BLE001
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
            rec["trace"] = traceback.format_exc(limit=3)[-600:]
            rec["screenshot"] = self.shot("error-" + re.sub(r"\W+", "-", name)[:30])
            self.issue("bug", f"Шаг «{name}» не удался", rec["error"], rec["screenshot"])
        rec["ms"] = round((time.perf_counter() - t0) * 1000)
        self.steps.append(rec)
        print(("  ✓ " if rec["ok"] else "  ✕ ") + f"{name} ({rec['ms']} мс)")
        return rec.get("result")

    # ---------- helpers ----------
    def audit(self, label: str) -> dict:
        a = self.page.evaluate(AUDIT_JS)
        if a["horizontal_overflow"]:
            self.issue("bug", "Горизонтальная прокрутка — страница шире экрана",
                       f"{label}: ширина документа {a['horizontal_overflow']}px при экране {a['viewport'][0]}px")
        if a["images_broken"]:
            self.issue("minor", "Битые картинки", f"{label}: {len(a['images_broken'])} шт., например {a['images_broken'][0]}")
        if a["clipped_texts"]:
            self.issue("minor", "Обрезанный текст", f"{label}: " + "; ".join(a["clipped_texts"][:5]))
        return a

    def wait_any(self, selectors: list[str], timeout: float = 15000):
        self.page.wait_for_selector(", ".join(selectors), timeout=timeout, state="visible")

    def modal_open(self, sel: str) -> bool:
        return self.page.evaluate(f"!!document.querySelector('{sel}.show')")


# =========================================================================== #
# Сценарии
# =========================================================================== #
def scenario_home(w: Walk, url: str) -> None:
    p = w.page

    def load():
        t0 = time.perf_counter()
        p.goto(url, wait_until="domcontentloaded", timeout=30000)
        w.wait_any(["#feed .card", "#feed .empty"], timeout=60000)
        t = round((time.perf_counter() - t0) * 1000)
        p.wait_for_timeout(800)
        info = {
            "load_ms": t,
            "greeting": p.text_content(".hero h1"),
            "status": p.text_content("#status"),
            "weather": (p.text_content("#weather") or "").strip()[:160],
            "topics_on_bar": p.locator("#pills .pill:not(.add)").all_text_contents(),
            "sections": p.locator("#feed .section h2").all_text_contents(),
            "screenshot": w.shot("home"),
            "screenshot_full": w.shot("home-full", full=True),
        }
        if t > 5000:
            w.issue("ux", "Главная грузится долго", f"{t} мс до первых карточек", info["screenshot"])
        if not p.locator("#feed .card").count():
            w.issue("bug", "Лента пустая", p.text_content("#feed") or "", info["screenshot"])
        if "недоступна" in info["weather"]:
            w.issue("minor", "Виджет погоды не загрузился", info["weather"], info["screenshot"])
        return info
    w.step("Открыть главную", load)
    w.step("Проверить вёрстку главной", lambda: w.audit("главная"))


def read_card(w: Walk, card, label: str) -> dict:
    p = w.page
    title = (card.locator(".title").text_content() or "").strip()
    card.scroll_into_view_if_needed()
    card.hover()
    p.wait_for_timeout(250)
    t0 = time.perf_counter()
    card.click(position={"x": 30, "y": 30})
    p.wait_for_selector("#reader.show", timeout=5000)
    w.wait_any(["#rContent .article p:not(.skeleton)", "#rContent .article .note"], timeout=25000)
    load_ms = round((time.perf_counter() - t0) * 1000)
    p.wait_for_timeout(400)
    paras = p.locator("#rContent .article p").all_text_contents()
    text_len = sum(len(x) for x in paras)
    res = {"title": title, "load_ms": load_ms, "paragraphs": len(paras), "text_chars": text_len,
           "source": p.text_content("#rMeta .src"), "screenshot": w.shot(f"reader-{label}")}
    if p.locator("#rContent .article .note").count():
        w.issue("ux", "В режиме чтения нет текста статьи", f"«{title[:80]}» — показано только описание", res["screenshot"])
    if load_ms > 6000:
        w.issue("ux", "Статья открывается долго", f"«{title[:60]}»: {load_ms} мс", res["screenshot"])
    if p.is_visible("#rSumBtn"):
        p.click("#rSumBtn")
        p.wait_for_timeout(700)
        tldr = p.locator("#rSummary li").all_text_contents()
        res["summary"] = tldr
        res["screenshot_summary"] = w.shot(f"reader-{label}-summary")
        dangling = [s for s in tldr if re.match(r"^(По (его|её|ее|их) словам|Он |Она |Они |Это |Эти |При этом|Кроме того|Однако)", s)]
        if dangling and tldr.index(dangling[0]) == 0:
            w.issue("ux", "Краткое содержание начинается со ссылки на неизвестное", dangling[0][:150], res["screenshot_summary"])
    else:
        res["summary"] = None
    # дочитать до конца
    p.locator("#reader .modal").evaluate("e => e.scrollTo(0, e.scrollHeight)")
    p.wait_for_timeout(300)
    res["screenshot_bottom"] = w.shot(f"reader-{label}-bottom")
    p.keyboard.press("Escape")
    p.wait_for_timeout(450)
    if w.modal_open("#reader"):
        w.issue("bug", "Окно новости не закрылось по Esc", title[:80])
        p.click("#reader [data-close]")
    return res


def scenario_reading(w: Walk, persona: dict) -> None:
    p = w.page
    cards = p.locator("#feed .card")
    total = cards.count()
    if not total:
        return
    picks = [0] + w.rnd.sample(range(1, total), min(persona["reads"] - 1, max(0, total - 1)))
    for k, i in enumerate(picks):
        w.step(f"Прочитать новость №{k + 1}", lambda i=i, k=k: read_card(w, p.locator("#feed .card").nth(i), str(k + 1)))

    def check_read():
        n = p.locator("#feed .card.read").count()
        if n == 0:
            w.issue("bug", "Прочитанные новости не отмечаются", "после чтения ни одна карточка не стала «прочитанной»")
        return {"cards_marked_read": n, "status": p.text_content("#status")}
    w.step("Проверить отметки «прочитано»", check_read)


def scenario_save(w: Walk) -> None:
    p = w.page

    def save():
        card = p.locator("#feed .card:not(.read)").first
        card.scroll_into_view_if_needed()
        card.hover()
        p.wait_for_timeout(250)
        card.locator(".save-btn").click()
        p.wait_for_timeout(400)
        cnt = p.locator("#savedBtn .cnt").text_content() if p.locator("#savedBtn .cnt").count() else "0"
        p.click("#savedBtn")
        p.wait_for_selector("#savedModal.show", timeout=3000)
        p.wait_for_timeout(300)
        rows = p.locator("#sList .s-row").count()
        shot = w.shot("saved")
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        if rows == 0:
            w.issue("bug", "Сохранённая новость не появилась в списке", "", shot)
        return {"counter": cnt, "rows": rows, "screenshot": shot}
    w.step("Сохранить новость на потом", save)


def scenario_topics(w: Walk) -> None:
    p = w.page

    def toggle():
        pill = p.locator("#pills .pill:not(.add)").first
        name = (pill.locator(".nm").text_content() or "").strip()
        p.evaluate("window.scrollTo(0, 0)")
        pill.scroll_into_view_if_needed()
        p.wait_for_timeout(300)
        before = p.locator("#feed .section").count()
        box = pill.bounding_box()
        p.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
        p.wait_for_timeout(800)
        after = p.locator("#feed .section").count()
        shot = w.shot("topic-off")
        p.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
        p.wait_for_timeout(800)
        if after >= before:
            w.issue("bug", "Выключение темы не убирает её из ленты", f"тема «{name}»: секций было {before}, стало {after}", shot)
        return {"topic": name, "sections_before": before, "sections_after_off": after, "screenshot": shot}
    w.step("Выключить и включить тему", toggle)

    def catalog():
        p.click("#pills .pill.add")
        p.wait_for_selector("#topicsModal.show", timeout=3000)
        p.wait_for_timeout(300)
        res = {"tiles": p.locator("#tGrid .tile").count(), "counter": p.text_content("#tCounter"), "screenshot": w.shot("topics-catalog")}
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        return res
    w.step("Открыть каталог тем «+ Темы»", catalog)


def scenario_navigation(w: Walk) -> None:
    p = w.page

    def more():
        btn = p.locator(".more-btn").first
        if not btn.count():
            return {"skipped": "нет кнопок «Ещё»"}
        btn.scroll_into_view_if_needed()
        before = p.locator("#feed .card").count()
        btn.click()
        p.wait_for_timeout(600)
        after = p.locator("#feed .card").count()
        if after <= before:
            w.issue("bug", "Кнопка «Ещё N новостей» ничего не показывает", f"карточек было {before}, стало {after}")
        return {"cards_before": before, "cards_after": after, "screenshot": w.shot("more-expanded")}
    w.step("Раскрыть «Ещё N новостей»", more)

    def rail():
        p.evaluate("window.scrollTo(0, 1400)")
        p.wait_for_timeout(700)
        visible = p.evaluate("document.getElementById('rail').classList.contains('show')")
        links = p.locator("#rail a")
        res = {"rail_visible": visible, "rail_items": links.count()}
        if not visible or not links.count():
            w.issue("ux", "Закладки тем не появились при прокрутке", "")
            return res
        target = links.last.get_attribute("data-target")
        links.last.click()
        p.wait_for_timeout(1100)
        res["jump_target"] = target
        res["target_top_px"] = p.evaluate(f"Math.round(document.getElementById('{target}').getBoundingClientRect().top)")
        res["active"] = p.evaluate("document.querySelector('#rail a.on')?.dataset.target")
        res["screenshot"] = w.shot("rail-jump")
        if res["active"] != target:
            w.issue("minor", "Закладка не подсветилась после перехода", f"цель {target}, подсвечено {res['active']}", res["screenshot"])
        return res
    w.step("Перейти к теме через закладки", rail)

    def to_top():
        btn = p.locator("#toTop")
        if not p.evaluate("document.getElementById('toTop').classList.contains('show')"):
            p.evaluate("window.scrollTo(0, 1500)")
            p.wait_for_timeout(500)
        t0 = time.perf_counter()
        btn.click()
        p.wait_for_function("window.scrollY === 0", timeout=3000)
        return {"scroll_ms": round((time.perf_counter() - t0) * 1000)}
    w.step("Кнопка «Наверх»", to_top)


def scenario_regions_theme(w: Walk) -> None:
    p = w.page
    for region in ("en", "kz", "ru"):
        def go(region=region):
            p.click(f"#regionSeg button[data-region={region}]")
            p.wait_for_timeout(1200)
            n = p.locator("#feed .card").count()
            shot = w.shot(f"region-{region}")
            if n == 0:
                w.issue("ux", f"В режиме {region.upper()} нет новостей", p.text_content("#feed")[:200] if p.text_content("#feed") else "", shot)
            return {"cards": n, "sections": p.locator("#feed .section h2").all_text_contents(), "screenshot": shot}
        w.step(f"Переключить источники на {region.upper()}", go)

    def theme():
        before = p.evaluate("document.documentElement.dataset.theme")
        p.click("#themeBtn")
        p.wait_for_timeout(500)
        after = p.evaluate("document.documentElement.dataset.theme")
        shot = w.shot(f"theme-{after}")
        a = w.audit(f"тема {after}")
        p.click("#themeBtn")
        p.wait_for_timeout(300)
        if before == after:
            w.issue("bug", "Кнопка смены темы не работает", "")
        return {"from": before, "to": after, "screenshot": shot, "audit": a}
    w.step("Сменить светлую/тёмную тему", theme)


def scenario_hide_source(w: Walk) -> None:
    p = w.page

    def hide():
        card = p.locator("#feed .card").nth(1)
        card.scroll_into_view_if_needed()
        card.click(position={"x": 30, "y": 30})
        p.wait_for_selector("#reader.show", timeout=5000)
        p.wait_for_timeout(600)
        btn = p.locator("#rExtra .danger")
        if not btn.count():
            p.keyboard.press("Escape")
            return {"skipped": "нет кнопки скрытия"}
        label = btn.text_content()
        btn.click()
        p.wait_for_timeout(700)
        toast = p.text_content("#toast")
        shot = w.shot("source-hidden")
        undo = p.locator("#toast button")
        if undo.count() and undo.is_visible():
            undo.click()
            p.wait_for_timeout(700)
        else:
            w.issue("ux", "Нет кнопки «Отменить» после скрытия источника", toast or "", shot)
        return {"button": label, "toast": toast, "screenshot": shot}
    w.step("Скрыть источник и отменить", hide)


def scenario_search(w: Walk, persona: dict) -> None:
    p = w.page
    q = w.rnd.choice(persona["queries"])

    def search():
        p.keyboard.press("Control+KeyK")
        p.wait_for_selector("#searchModal.show", timeout=3000)
        p.wait_for_timeout(300)
        home = w.shot("search-empty")
        p.keyboard.type(q, delay=40)
        t0 = time.perf_counter()
        p.keyboard.press("Enter")
        w.wait_any(["#sBody .s-res", "#sBody .s-note"], timeout=30000)
        p.wait_for_function("!document.querySelector('#sBody .s-skel')", timeout=30000)
        ms = round((time.perf_counter() - t0) * 1000)
        p.wait_for_timeout(300)
        labels = p.locator("#sBody .s-label").all_text_contents()
        rows = p.locator("#sBody .s-res")
        res = {"query": q, "ms": ms, "results": rows.count(), "blocks": labels,
               "first_titles": rows.locator("b").all_text_contents()[:5], "screenshot_empty": home, "screenshot": w.shot("search-results")}
        if not rows.count():
            w.issue("ux", "Поиск ничего не нашёл", f"запрос «{q}»: {p.text_content('#sBody')[:200]}", res["screenshot"])
        if ms > 8000:
            w.issue("ux", "Поиск отвечает долго", f"«{q}»: {ms} мс", res["screenshot"])
        return res
    r = w.step(f"Найти «{q}»", search)
    if not r or not r.get("results"):
        p.keyboard.press("Escape")
        return

    def open_result():
        rows = p.locator("#sBody .s-res")
        # предпочитаем результат из интернета (последний блок), иначе первый
        idx = 0
        if p.locator("#sBody .s-label", has_text="В интернете").count():
            idx = rows.count() - p.locator("#sBody .s-label:has-text('В интернете') ~ .s-res").count()
        title = rows.nth(idx).locator("b").text_content()
        t0 = time.perf_counter()
        rows.nth(idx).click()
        p.wait_for_selector("#reader.show", timeout=5000)
        w.wait_any(["#rContent .article p:not(.skeleton)", "#rContent .article .note"], timeout=30000)
        ms = round((time.perf_counter() - t0) * 1000)
        p.wait_for_timeout(400)
        paras = p.locator("#rContent .article p").count()
        shot = w.shot("search-reader")
        if p.locator("#rContent .article .note").count():
            w.issue("ux", "Найденную статью не удалось открыть внутри сайта", title[:100], shot)
        p.keyboard.press("Escape")
        p.wait_for_timeout(500)
        back = w.modal_open("#searchModal")
        if not back:
            w.issue("minor", "После закрытия статьи не вернулись к результатам поиска", "")
        p.keyboard.press("Escape")
        p.wait_for_timeout(300)
        return {"title": title, "ms": ms, "paragraphs": paras, "returned_to_results": back, "screenshot": shot}
    w.step("Открыть результат поиска внутри сайта", open_result)


def scenario_footer(w: Walk) -> None:
    p = w.page

    def footer():
        p.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        p.wait_for_timeout(400)
        p.click("#sources summary")
        p.wait_for_timeout(400)
        summary = p.text_content("#srcSummary")
        bad = p.locator("#srcList li:has(.bad)").all_text_contents()
        shot = w.shot("sources")
        if bad:
            w.issue("info", f"Не отвечают источники: {len(bad)}", "; ".join(re.sub(r"\s+", " ", b)[:60] for b in bad[:20]), shot)
        return {"summary": summary, "failed": len(bad), "screenshot": shot}
    w.step("Посмотреть список источников", footer)


def scenario_refresh(w: Walk) -> None:
    p = w.page

    def refresh():
        p.evaluate("window.scrollTo(0, 0)")
        t0 = time.perf_counter()
        p.click("#refreshBtn")
        p.wait_for_function("!document.getElementById('refreshBtn').disabled", timeout=240000)
        ms = round((time.perf_counter() - t0) * 1000)
        p.wait_for_timeout(800)
        return {"ms": ms, "status": p.text_content("#status"), "screenshot": w.shot("after-refresh")}
    w.step("Нажать «Обновить» и дождаться", refresh)


def scenario_mobile(w: Walk, url: str, pw, browser) -> None:
    ctx = browser.new_context(**pw.devices["iPhone 13"], locale="ru-RU")
    page = ctx.new_page()
    w.attach(page, "mobile")

    def home():
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        w.wait_any(["#feed .card", "#feed .empty"], timeout=60000)
        page.wait_for_timeout(800)
        a = w.audit("мобильная главная")
        if a["small_tap_targets"]:
            w.issue("ux", "Мелкие кнопки на телефоне (меньше 32px)", ", ".join(a["small_tap_targets"][:8]))
        return {"screenshot": w.shot("home"), "screenshot_full": w.shot("home-full", full=True), "audit": a}
    w.step("Открыть сайт на телефоне", home)

    def read():
        card = page.locator("#feed .card").first
        card.scroll_into_view_if_needed()
        card.tap()
        page.wait_for_selector("#reader.show", timeout=5000)
        w.wait_any(["#rContent .article p:not(.skeleton)", "#rContent .article .note"], timeout=25000)
        page.wait_for_timeout(400)
        shot = w.shot("reader")
        page.locator("#reader [data-close]").tap()
        page.wait_for_timeout(400)
        return {"screenshot": shot}
    w.step("Прочитать новость на телефоне", read)

    def topics_scroll():
        el = page.locator("#pills")
        sw, cw = el.evaluate("e => [e.scrollWidth, e.clientWidth]")
        add_first = page.evaluate("getComputedStyle(document.querySelector('#pills .pill.add')).order") == "-1"
        return {"scrollable": sw > cw, "add_button_first": add_first, "screenshot": w.shot("topics")}
    w.step("Строка тем на телефоне", topics_scroll)
    ctx.close()


# =========================================================================== #
def main() -> None:
    ap = argparse.ArgumentParser(description="Имитация пользователя сайта «Волна»")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--persona", choices=list(PERSONAS), default="morning")
    ap.add_argument("--out", default="ux-report")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--refresh", action="store_true", help="нажать «Обновить» (сбор новостей, 1–3 минуты)")
    ap.add_argument("--headed", action="store_true", help="показать окно браузера")
    ap.add_argument("--no-mobile", action="store_true")
    args = ap.parse_args()

    persona = PERSONAS[args.persona]
    seed = args.seed if args.seed is not None else int(time.time())
    out = Path(args.out) / dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out.mkdir(parents=True, exist_ok=True)
    w = Walk(out, random.Random(seed))
    started = time.time()
    print(f"Пользователь: {persona['name']}\nОтчёт: {out}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed, slow_mo=120 if args.headed else 0)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", color_scheme="dark")
        if persona.get("region"):
            ctx.add_init_script(f"localStorage.setItem('volna.region', JSON.stringify('{persona['region']}'))")
        page = ctx.new_page()
        w.attach(page, "desktop")
        try:
            page.goto(args.url, timeout=10000)
        except Exception:  # noqa: BLE001
            sys.exit(f"Сайт {args.url} не открывается. Запустите сервер: python run.py")

        scenario_home(w, args.url)
        if args.refresh:
            scenario_refresh(w)
        scenario_reading(w, persona)
        scenario_save(w)
        scenario_topics(w)
        scenario_navigation(w)
        scenario_search(w, persona)
        scenario_hide_source(w)
        scenario_regions_theme(w)
        scenario_footer(w)
        ctx.close()
        if not args.no_mobile:
            scenario_mobile(w, args.url, pw, browser)
        browser.close()

    js_errors = [c for c in w.console if c["type"] == "error"]
    if js_errors:
        w.issue("minor", f"Ошибки в консоли браузера: {len(js_errors)}", "; ".join(c["text"][:100] for c in js_errors[:5]))
    for f in w.failed:
        w.issue("bug", "Запрос к серверу завершился ошибкой", f"{f['status']} {f['url']}")

    report = {
        "persona": persona["name"], "url": args.url, "seed": seed,
        "started": dt.datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "duration_s": round(time.time() - started, 1),
        "steps_total": len(w.steps), "steps_failed": sum(1 for s in w.steps if not s["ok"]),
        "issues": w.issues, "steps": w.steps, "console": w.console[:50], "failed_requests": w.failed[:50],
        "screenshots": sorted(p.name for p in out.glob("*.png")),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nГотово за {report['duration_s']} с: шагов {report['steps_total']}, не удалось {report['steps_failed']}, "
          f"замечаний {len(w.issues)}.\nОтчёт: {out / 'report.json'}")


if __name__ == "__main__":
    main()
