import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "analytics_state.json").read_text(
    encoding="utf-8"
)
RUNS = [
    {
        "id": 4,
        "created": "2026-11-08T06:30:00+05:00",
        "status": "done",
        "model": "qwen3-6",
        "checklist_version": 3,
        "total": 16,
        "done": 16,
        "cost": 0.016,
        "errors_count": 0,
        "force": True,
        "skipped": 1,
    },
    {
        "id": 3,
        "created": "2026-11-08T05:10:00+05:00",
        "status": "done",
        "model": "jev",
        "checklist_version": 3,
        "total": 16,
        "done": 15,
        "cost": 0.02,
        "errors_count": 1,
        "force": False,
        "skipped": 0,
    },
]
COMPARE = {
    "a": 3,
    "b": 4,
    "pairs": 16,
    "agree": 0.875,
    "criteria": [
        {"cid": "04", "pairs": 2, "agree": 0.5, "mean_step_diff": 1.0},
        {"cid": "07", "pairs": 2, "agree": 1.0, "mean_step_diff": None},
    ],
    "diffs": [
        {"dialog": "call-024", "cid": "04", "a": 15, "b": 10},
        {"dialog": "p1-kz-015", "cid": "07", "a": "yes", "b": "no"},
    ],
}
PRODUCTS = [
    {
        "id": "brokerage",
        "name": "Брокерский счёт",
        "dialogs": 6,
        "scored": 5,
        "avg_total": 81.2,
        "gross_errors": 1,
        "needs_review": 2,
        "weakest": [{"cid": "04", "name": "Консультация", "share": 0.6}],
    },
    {
        "id": "cards",
        "name": "Карты",
        "dialogs": 4,
        "scored": 0,
        "avg_total": None,
        "gross_errors": 0,
        "needs_review": 0,
        "weakest": [],
    },
]


def open_analytics(page: Page, web_url: str) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    requests: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.on(
        "request",
        lambda r: requests.append(f"{r.method} {r.url.split('/api', 1)[1]}") if "/api/" in r.url else None,
    )
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route(
        "**/api/runs", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(RUNS))
    )
    page.route(
        re.compile(r".*/api/runs/compare\?.*"),
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(COMPARE)),
    )
    page.route(
        "**/api/products/stats",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(PRODUCTS)),
    )
    page.goto(f"{web_url}/#/analytics")
    expect(page.locator('[data-view="analytics"] h1')).to_have_text("Аналитика")
    return problems, requests


def new_paths(requests: list[str]) -> list[str]:
    return [r for r in requests if re.match(r"GET /(runs|products|scores)", r)]


def test_runs_tab_loads_journal_on_click_and_compares_two_latest(page: Page, web_url: str) -> None:
    problems, requests = open_analytics(page, web_url)
    expect(page.locator(".lens a strong").first).to_be_visible()
    assert new_paths(requests) == []  # обзор не зовёт новые пути: у сервера защиты их может не быть
    page.click('[data-act="tab"][data-tab="runs"]')
    expect(page).to_have_url(re.compile(r"#/analytics\?tab=runs$"))
    rows = page.locator('[aria-label="Журнал прогонов"] tbody tr')
    expect(rows).to_have_count(2)
    expect(rows.first).to_contain_text("заново")
    expect(rows.first.get_by_label("Прогон 4 как Б")).to_be_checked()
    expect(rows.nth(1).get_by_label("Прогон 3 как А")).to_be_checked()
    expect(rows.nth(1).locator("td").nth(7)).to_have_text("1")
    page.click('[data-act="compare"]')
    expect(page.locator('[aria-label="Сравнение прогонов"]')).to_contain_text(
        "Общих пар «диалог, критерий»: 16. Совпадение ответов: 88%"
    )
    diffs = page.locator('[aria-label="Расхождения"] tbody tr')
    expect(diffs).to_have_count(2)
    expect(diffs.first.locator("td")).to_have_text(
        [re.compile("."), re.compile("^04"), "15 из 20", "10 из 20"]
    )
    expect(diffs.nth(1).locator("td").nth(2)).to_have_text("Да")
    expect(diffs.first.locator('a[href="#/d/call-024"]')).to_be_visible()
    assert "GET /runs/compare?a=3&b=4" in requests
    assert problems == []


def test_compare_is_disabled_with_reason_when_same_run_picked(page: Page, web_url: str) -> None:
    open_analytics(page, web_url)
    page.click('[data-act="tab"][data-tab="runs"]')
    page.get_by_label("Прогон 4 как А").check()
    expect(page.locator('[data-act="compare"]')).to_be_disabled()
    expect(page.locator('[aria-label="Журнал прогонов"]')).to_contain_text("Выберите два разных прогона.")


def test_products_tab_loads_stats_on_click(page: Page, web_url: str) -> None:
    problems, requests = open_analytics(page, web_url)
    page.click('[data-act="tab"][data-tab="products"]')
    rows = page.locator('[aria-label="Качество по продуктам"] tbody tr')
    expect(rows).to_have_count(2)
    expect(rows.first.locator("td")).to_have_text(
        ["Брокерский счёт", "6", "5", "81,20", "1", "2", "04 Консультация 60%"]
    )
    expect(rows.nth(1).locator("td").nth(3)).to_have_text("—")
    expect(page.locator('[aria-label="Средний итог по продуктам"] li')).to_have_text(
        ["Брокерский счёт: 81,20"]
    )
    assert new_paths(requests) == ["GET /products/stats"]
    page.click('[data-act="tab"][data-tab="overview"]')
    expect(page.locator('[aria-label="Результат по критериям"]')).to_be_visible()
    assert problems == []


def test_scores_export_downloads_on_click_only(page: Page, web_url: str) -> None:
    hits: list[str] = []

    def export(route: Route) -> None:
        hits.append(route.request.url.split("/api", 1)[1])
        route.fulfill(
            status=200,
            content_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="cqa-scores-v3.csv"'},
            body="﻿ID;Итог\n",
        )

    page.route(re.compile(r".*/api/scores/export\?.*"), export)
    open_analytics(page, web_url)
    assert hits == []
    with page.expect_download() as dl:
        page.click('[data-act="download"][data-kind="scores-wide"]')
    assert dl.value.suggested_filename == "cqa-scores-v3.csv"
    assert hits == ["/scores/export?format=csv&shape=wide"]


@pytest.mark.parametrize("tab", ["runs", "products"])
def test_tabs_fit_390px(page: Page, web_url: str, tab: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    problems, _ = open_analytics(page, web_url)
    page.click(f'[data-act="tab"][data-tab="{tab}"]')
    expect(page.locator("main table").first).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
