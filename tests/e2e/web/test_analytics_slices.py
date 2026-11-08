import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "analytics_state.json").read_text(
    encoding="utf-8"
)
DEFS = {"n": "n — число оценённых диалогов выборки.", "uplift": "uplift = avg_total_if_max − средний итог."}
HEAD = {"filters": {}, "n": 10, "min_n": 5, "definitions": DEFS}


def cnt(k: int, n: int) -> dict:
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "low_n": n < 5}


def cell(share: float, n: int) -> dict:
    return {"n": n, "share": share, "low_n": n < 5}


STUBS = {
    "drivers": {
        "base": 78.5,
        "drivers": [
            {
                "id": "04",
                "name": "Корректная и полная консультация",
                "n": 10,
                "at_max": {"n": 5, "avg_total": 88.0, "gross": 0.0},
                "below_max": {"n": 5, "avg_total": 69.0, "gross": 0.2},
                "gap": 19.0,
                "low_n": False,
                "r": 0.81,
                "lowest": cnt(4, 10),
                "uplift": 4.1,
                "avg_total_if_max": 82.6,
                "what_if": "Если поднять «Корректная и полная консультация» до максимума во всех 10 "
                "диалогах, где он применим, средний итог вырастет на 4,10 балла: с 78,50 до 82,60.",
            },
            {
                "id": "07",
                "name": "Завершение",
                "n": 10,
                "at_max": {"n": 7, "avg_total": 80.0, "gross": 0.0},
                "below_max": {"n": 3, "avg_total": 75.0, "gross": 0.0},
                "gap": 5.0,
                "low_n": True,
                "r": 0.3,
                "lowest": cnt(1, 10),
                "uplift": 0.9,
                "avg_total_if_max": 79.4,
                "what_if": "Если поднять «Завершение» до максимума…",
            },
        ],
    },
    "heatmap": {
        "columns": [{"id": "04", "name": "Корректная и полная консультация", "n": 10, "share": 0.7}],
        "rows": [
            {
                "key": "RU",
                "label": "RU",
                "n": 7,
                "low_n": False,
                "avg_total": 80.1,
                "cells": {"04": cell(0.8, 7)},
            },
            {
                "key": None,
                "label": "Не указан",
                "n": 3,
                "low_n": True,
                "avg_total": 74.0,
                "cells": {"04": cell(0.5, 3)},
            },
        ],
    },
    "trend": {
        "criteria": [{"id": "04", "name": "Корректная и полная консультация"}],
        "points": [
            {
                "period": f"2026-11-0{d}",
                "n": n,
                "low_n": n < 5,
                "avg_total": a,
                "gross": cnt(0, n),
                "no_next_step": cnt(1, n),
                "needs_review": cnt(1, n),
                "criteria": {"04": cell(0.7, n)},
            }
            for d, n, a in ((6, 3, 70.0), (7, 7, 81.2))
        ],
    },
    "appeals": {
        "summary": {
            "filed": 6,
            "reviews": 1,
            "pending": 1,
            "closed": 0,
            "decided": 6,
            "changed": 3,
            "confirmed": 3,
            "changed_share": 0.5,
            "low_n": False,
            "median_hours": 5.5,
            "timed": 5,
        },
        "criteria": [
            {
                "id": "04",
                "name": "Корректная и полная консультация",
                "filed": 3,
                "reviews": 0,
                "decided": 3,
                "changed": 2,
                "confirmed": 1,
                "changed_share": 0.6667,
                "low_n": True,
            }
        ],
        "reviewers": [
            {
                "reviewer": "Айгерим",
                "decided": 6,
                "changed": 3,
                "changed_share": 0.5,
                "low_n": False,
                "median_hours": 5.5,
                "timed": 5,
            }
        ],
    },
    "model": {
        "criteria": [
            {
                "id": "04",
                "name": "Корректная и полная консультация",
                "results": 10,
                "second_opinion": cnt(8, 10),
                "ev_fail": cnt(1, 10),
                "jev_unsure": cnt(0, 0),
                "manual": cnt(1, 10),
            }
        ],
        "cost": [{"period": "2026-11-07", "n": 7, "avg_usd": 0.0016, "avg_s": 4.2, "low_n": False}],
    },
}


def open_analytics(page: Page, web_url: str) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    calls: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None)

    def analytics(route: Route) -> None:
        path = route.request.url.split("/api", 1)[1]
        calls.append(path)
        name = re.match(r"/analytics/(\w+)", path)[1]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({**HEAD, "name": name, **STUBS[name]}),
        )

    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route(re.compile(r".*/api/analytics/\w+(\?.*)?$"), analytics)
    page.goto(f"{web_url}/#/analytics")
    expect(page.locator(".lens a strong").first).to_be_visible()
    return problems, calls


def test_slices_tab_loads_analytics_on_open_and_keeps_filters_in_url(page: Page, web_url: str) -> None:
    problems, calls = open_analytics(page, web_url)
    assert calls == []  # обзор не зовёт /analytics/*: у сервера защиты этих путей может не быть
    page.click('[data-act="tab"][data-tab="slices"]')
    expect(page).to_have_url(re.compile(r"#/analytics\?tab=slices$"))

    drivers = page.locator('[aria-label="Что сильнее всего снижает итог"]')
    expect(drivers.locator('[data-act="headline"]')).to_contain_text(
        "Исправлять первым: «Корректная и полная консультация», +4,10 к среднему итогу 78,50."
    )
    expect(drivers.locator('tr[data-cid="04"]')).to_contain_text("средний итог вырастет на 4,10 балла")
    expect(drivers.locator('tr[data-cid="07"]')).to_contain_text("мало данных (n=3, нужно ≥5)")
    expect(drivers.locator('tr[data-cid="04"] a')).to_have_attribute("href", "#/queue?lost=04")

    heat = page.locator('[aria-label="Тепловая карта"]')
    expect(heat.locator("tbody tr")).to_have_count(2)
    expect(heat.locator('tbody tr[data-key=""]')).to_contain_text("Не указан")
    expect(heat.locator("tbody tr").nth(1).locator(".heat.low")).to_contain_text("мало данных, n=3")
    expect(page.locator('[aria-label="Точки тренда"] li[data-low]')).to_have_text(
        "2026-11-06: 70,00, n=3, мало данных (n=3, нужно ≥5)"
    )
    expect(page.locator('[aria-label="Апелляции по критериям"] tbody tr')).to_contain_text(
        "мало данных (n=3, нужно ≥5)"
    )
    expect(
        page.locator('[aria-label="Сигналы модели по критериям"] [data-metric="second_opinion"]')
    ).to_contain_text("80% 8 из 10")
    assert sorted(calls) == [
        "/analytics/appeals",
        "/analytics/drivers",
        "/analytics/heatmap?by=operator",
        "/analytics/model",
        "/analytics/trend?by=day",
    ]

    page.click('[data-act="by"][data-by="lang"]')
    expect(page).to_have_url(re.compile(r"by=lang"))
    page.locator('[data-act="filter"][data-key="ch"]').select_option("call")
    expect(page).to_have_url(re.compile(r"#/analytics\?tab=slices&by=lang&ch=call$"))
    expect(drivers.locator('tr[data-cid="04"] a')).to_have_attribute("href", "#/queue?lost=04&ch=call")
    assert "/analytics/heatmap?by=lang&ch=call" in calls
    assert "/analytics/drivers?ch=call" in calls
    assert problems == []


def test_slices_tab_fits_390px(page: Page, web_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    problems, _ = open_analytics(page, web_url)
    page.click('[data-act="tab"][data-tab="slices"]')
    expect(page.locator('[aria-label="Тренд"] canvas')).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
