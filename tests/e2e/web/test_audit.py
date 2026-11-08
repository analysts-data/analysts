import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(encoding="utf-8")
EMPLOYEES = [
    {"id": "e1", "name": "Алия К.", "role": "operator", "team": "RU", "active": True},
    {"id": "e2", "name": "Борис П.", "role": "reviewer", "team": "QA", "active": True},
]
ROWS = [
    {"id": 7, "at": "2026-11-08T06:41:12+05:00", "actor_id": "e2", "actor_name": "Борис П.", "role": "reviewer", "action": "appeal.decide", "target_type": "appeal", "target_id": "a1", "details": {"verdict": "changed"}},
    {"id": 6, "at": "2026-11-08T06:20:00+05:00", "actor_id": "e1", "actor_name": "Алия К.", "role": "operator", "action": "appeal.file", "target_type": "dialog", "target_id": "call-024", "details": {"cid": "04"}},
    {"id": 5, "at": "2026-11-07T18:02:00+05:00", "actor_id": None, "actor_name": "без входа", "role": "", "action": "dataset.upload", "target_type": "set", "target_id": "", "details": {}},
]
USAGE = {
    "filters": {"since": "2026-11-01", "role": None},
    "events": 120,
    "active_users": [{"day": "2026-11-07", "users": 2}, {"day": "2026-11-08", "users": 3}],
    "screens": [{"page": "queue", "events": 70, "views": 12, "median_ms": 41000}, {"page": "d", "events": 30, "views": 9, "median_ms": None}],
    "actions": [{"act": "open", "n": 30}],
    "funnels": [{"name": "Открыл диалог → подал апелляцию", "started": 10, "converted": 2, "rate": 0.2, "median_s": 95.0}],
    "errors": [{"page": "card", "code": "run_failed", "n": 1}],
    "exports": [{"kind": "checklist-csv", "n": 2}],
    "reports": [{"kind": "html", "n": 1}],
}


def watch(page: Page) -> list[str]:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route(re.compile(r".*/api/employees$"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(EMPLOYEES)))
    return problems


def test_audit_filters_go_to_the_server_and_rows_link_to_objects(page: Page, web_url: str) -> None:
    problems = watch(page)
    queries: list[dict[str, list[str]]] = []

    def audit(route: Route) -> None:
        q = parse_qs(urlparse(route.request.url).query)
        if q.get("format") == ["csv"]:
            route.fulfill(status=200, content_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit.csv"'}, body="﻿id;at\n7;x\n")
            return
        queries.append(q)
        rows = [r for r in ROWS if not q.get("actor") or r["actor_id"] == q["actor"][0]]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(rows))

    page.route(re.compile(r".*/api/audit\?.*"), audit)
    page.goto(f"{web_url}/#/audit")
    rows = page.locator('[aria-label="Действия"] tbody tr')
    expect(rows).to_have_count(3)
    expect(rows.first.locator("td")).to_have_text(["08.11 06:41", "Борис П.", "Проверяющий", "Решил апелляцию", "апелляция a1", "verdict: changed"])
    expect(rows.nth(1).locator('a[href="#/d/call-024"]')).to_have_text("диалог call-024")
    expect(rows.nth(2)).to_contain_text("без входа")
    assert queries[0] == {"limit": ["100"]}

    page.locator("[data-act=filter-actor]").select_option("e1")
    expect(rows).to_have_count(1)
    expect(page).to_have_url(re.compile(r"#/audit\?actor=e1"))
    assert queries[-1] == {"actor": ["e1"], "limit": ["100"]}
    page.locator("[data-act=filter-action]").select_option("appeal.file")
    expect(page).to_have_url(re.compile(r"action=appeal.file"))
    assert queries[-1] == {"actor": ["e1"], "action": ["appeal.file"], "limit": ["100"]}

    with page.expect_download() as dl:
        page.click('[data-act="download"][data-kind="audit-csv"]')
    assert dl.value.suggested_filename == "audit.csv"
    assert problems == []


def test_audit_link_from_employee_page_opens_filtered_log(page: Page, web_url: str) -> None:
    watch(page)
    seen: list[str] = []
    page.route(re.compile(r".*/api/audit\?.*"), lambda r: (seen.append(r.request.url), r.fulfill(status=200, content_type="application/json", body="[]")))
    page.goto(f"{web_url}/#/audit?actor=e2")
    expect(page.locator("[data-act=filter-actor]")).to_have_value("e2")
    expect(page.locator('[aria-label="Действия"]')).to_contain_text("По этим фильтрам действий нет.")
    page.get_by_role("button", name="Сбросить фильтры").first.click()
    expect(page).to_have_url(re.compile(r"#/audit$"))
    assert "actor=e2" in seen[0]


def test_usage_shows_summary_screens_funnels_and_errors(page: Page, web_url: str) -> None:
    problems = watch(page)
    seen: list[str] = []

    def usage(route: Route) -> None:
        seen.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(USAGE))

    page.route(re.compile(r".*/api/usage\?.*"), usage)
    page.goto(f"{web_url}/#/usage")
    expect(page.locator('[data-view="usage"] h1')).to_have_text("Использование")
    expect(page.locator('[aria-label="Сводка"] strong')).to_have_text(["120", "3", "21"])
    screens = page.locator('[aria-label="Экраны"] tbody tr')
    expect(screens.first.locator("td")).to_have_text(["Диалоги", "12", "70", "00:41"])
    expect(screens.nth(1).locator("td").last).to_have_text("—")
    expect(page.locator('[aria-label="Воронки"] tbody tr').first.locator("td")).to_have_text(["Открыл диалог → подал апелляцию", "10", "2", "20%", "01:35"])
    expect(page.locator('[aria-label="Ошибки на экранах"]')).to_contain_text("Карточка разговора: run_failed")
    expect(page.locator('[aria-label="Активные сотрудники по дням"] li')).to_have_text(["07.11: 2", "08.11: 3"])
    assert "since=" in seen[0]
    page.locator("[data-act=filter-role]").select_option("qa")
    expect(page).to_have_url(re.compile(r"role=qa"))
    assert "role=qa" in seen[-1]
    assert problems == []


@pytest.mark.parametrize("route", ["#/audit", "#/usage"])
def test_audit_and_usage_fit_390px(page: Page, web_url: str, route: str) -> None:
    problems = watch(page)
    page.route(re.compile(r".*/api/audit\?.*"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(ROWS)))
    page.route(re.compile(r".*/api/usage\?.*"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(USAGE)))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{web_url}/{route}")
    expect(page.locator("main h1")).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
