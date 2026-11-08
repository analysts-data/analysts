"""Экран «Алерты»: фильтры статуса и важности, «Принять», «Решить» с заметкой, «Назначить», «Почему»,
переход к объекту.

Ответы /api/alerts — по черновику контракта (openspec/changes/react-frontend/helpers-ops.md),
объектом {items, counts}.
"""

import copy
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Locator, Page, Route, expect

pytestmark = pytest.mark.e2e

STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)
EMPLOYEES = [
    {"id": "e1", "name": "Сауле Б.", "role": "qa", "team": "КК", "active": True},
    {"id": "e2", "name": "Марат Д.", "role": "reviewer", "team": "КК", "active": True},
]
BLANK = {"assignee": None, "resolved_by": None, "resolved_at": None, "note": None}
ALERTS = [
    {
        **BLANK,
        "id": "a3",
        "rule_id": "run_errors",
        "severity": "info",
        "title": "Прогон закончился с ошибками",
        "target_type": "run",
        "target_id": "12",
        "created": "2026-11-08T01:00:00Z",
        "status": "resolved",
        "note": "Перезапустили прогон",
        "resolved_by": "e1",
        "resolved_at": "2026-11-08T02:00:00Z",
    },
    {
        **BLANK,
        "id": "a2",
        "rule_id": "operator_low_total",
        "severity": "warning",
        "title": "Средний итог оператора ниже порога",
        "target_type": "operator",
        "target_id": "Алия К.",
        "created": "2026-11-08T02:00:00Z",
        "status": "ack",
        "assignee": "e2",
        "basis": {"rule": "Средний итог за 7 дней", "threshold": 70, "value": 64.5},
    },
    {
        **BLANK,
        "id": "a1",
        "rule_id": "gross_unreviewed",
        "severity": "critical",
        "title": "Грубая ошибка не проверена",
        "target_type": "dialog",
        "target_id": "p1-kz-015",
        "created": "2026-11-08T03:00:00Z",
        "status": "new",
        "basis": {
            "rule": "Грубая ошибка без проверки дольше порога",
            "threshold": "24 ч",
            "value": "26 ч",
            "lines": [{"n": 7, "text": "Это не мои проблемы"}],
        },
    },
]


class Alerts:
    """Подменяет /api/alerts как сервер: список с фильтрами и счётчиками; действия меняют алерт."""

    def __init__(self, page: Page) -> None:
        self.items: list[dict[str, Any]] = copy.deepcopy(ALERTS)
        self.calls: list[tuple[str, str, Any]] = []
        self.errors: list[str] = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.route(
            "**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE)
        )
        page.route("**/api/employees", lambda r: r.fulfill(json=EMPLOYEES))
        page.route("**/api/alerts**", self.handle)

    def handle(self, route: Route) -> None:
        req = route.request
        url = urlparse(req.url)
        parts = url.path.split("/")  # ['', 'api', 'alerts', id?, action?]
        body = req.post_data_json if req.post_data else None
        if req.method == "GET":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            self.calls.append(("GET", url.query, None))
            items = [
                a
                for a in self.items
                if q.get("status", a["status"]) == a["status"]
                and q.get("severity", a["severity"]) == a["severity"]
            ]
            counts = {s: sum(a["status"] == s for a in self.items) for s in ("new", "ack", "resolved")}
            return route.fulfill(json={"items": items, "counts": counts})
        alert = next(a for a in self.items if a["id"] == parts[3])
        self.calls.append((req.method, parts[4], body))
        if parts[4] == "ack":
            alert["status"] = "ack"
        elif parts[4] == "resolve":
            alert.update(
                status="resolved", note=body["note"], resolved_by="e1", resolved_at="2026-11-08T04:00:00Z"
            )
        elif parts[4] == "assignee":
            alert["assignee"] = body["assignee"]
        route.fulfill(json=alert)

    def writes(self) -> list[tuple[str, str, Any]]:
        return [c for c in self.calls if c[0] != "GET"]


def open_alerts(page: Page, web_url: str, route: str = "#/alerts") -> Alerts:
    api = Alerts(page)
    page.goto(f"{web_url}/{route}")
    expect(page.locator("[data-alert]").first).to_be_visible()
    return api


def row(page: Page, aid: str) -> Locator:
    return page.locator(f'tr[data-alert="{aid}"]')


def test_alerts_list_new_first_with_counts_and_server_filters(page: Page, web_url: str) -> None:
    api = open_alerts(page, web_url)
    rows = page.locator("[data-alert]")
    assert [el.get_attribute("data-alert") for el in rows.all()] == ["a1", "a2", "a3"]
    expect(page.locator('[data-view="alerts"]')).to_contain_text("Новых: 1, принятых: 1, решённых: 1.")
    expect(row(page, "a1")).to_contain_text("Критичный")
    expect(row(page, "a1")).to_contain_text("Новый")
    expect(page.locator("#bAlerts")).to_have_text("1")  # колокольчик в навигации — тот же ответ
    page.locator('[data-act="f-status"]').select_option("new")
    expect(page).to_have_url(re.compile(r"#/alerts\?status=new$"))
    expect(rows).to_have_count(1)
    page.locator('[data-act="f-severity"]').select_option("warning")
    expect(page.get_by_text("Под эти фильтры алертов нет.")).to_be_visible()
    assert ("GET", "status=new&severity=warning", None) in api.calls
    page.get_by_role("button", name="Сбросить фильтры").first.click()
    expect(rows).to_have_count(3)
    assert api.errors == []


def test_accept_posts_ack_and_alert_becomes_accepted(page: Page, web_url: str) -> None:
    api = open_alerts(page, web_url)
    row(page, "a1").locator('[data-act="ack"]').click()
    expect(row(page, "a1")).to_contain_text("Принят")
    expect(row(page, "a1").locator('[data-act="ack"]')).to_have_count(0)
    expect(page.locator("#toast")).to_contain_text("Алерт принят в работу.")
    assert api.writes() == [("POST", "ack", None)]


def test_resolve_needs_a_note_keeps_the_draft_and_posts_it(page: Page, web_url: str) -> None:
    api = open_alerts(page, web_url)
    row(page, "a1").locator('[data-act="resolve"]').click()
    dialog = page.get_by_role("dialog", name="Решить алерт")
    dialog.locator('[data-act="resolve-save"]').click()
    expect(dialog).to_contain_text("Напишите, что сделано")
    assert api.writes() == []
    dialog.get_by_label("Заметка").fill("Проверили, оператору назначено обучение")
    dialog.get_by_role("button", name="Отмена").click()
    row(page, "a1").locator('[data-act="resolve"]').click()
    expect(dialog.get_by_label("Заметка")).to_have_value("Проверили, оператору назначено обучение")
    dialog.locator('[data-act="resolve-save"]').click()
    expect(dialog).to_have_count(0)
    expect(row(page, "a1")).to_contain_text("Решён")
    assert api.writes() == [("POST", "resolve", {"note": "Проверили, оператору назначено обучение"})]
    assert api.errors == []


def test_assign_puts_employee_id(page: Page, web_url: str) -> None:
    api = open_alerts(page, web_url)
    expect(row(page, "a2").locator('[data-act="assign"]')).to_have_value("e2")
    row(page, "a1").locator('[data-act="assign"]').select_option(label="Марат Д.")
    expect(page.locator("#toast")).to_contain_text("Назначен: Марат Д.")
    assert api.writes() == [("PUT", "assignee", {"assignee": "e2"})]


def test_why_shows_server_basis_and_links_lead_to_the_object(page: Page, web_url: str) -> None:
    api = open_alerts(page, web_url)
    row(page, "a1").locator('[data-act="why"]').click()
    why = page.locator('[aria-label="Почему"]')
    for text in (
        "Правило",
        "Грубая ошибка без проверки дольше порога",
        "Порог",
        "24 ч",
        "Наблюдённое значение",
        "26 ч",
        "Это не мои проблемы",
    ):
        expect(why).to_contain_text(text)
    expect(why.get_by_role("link", name="Реплика 7")).to_have_attribute("href", "#/d/p1-kz-015?n=7")
    expect(row(page, "a2").locator('[data-act="target"]')).to_have_attribute(
        "href", "#/people/%D0%90%D0%BB%D0%B8%D1%8F%20%D0%9A."
    )
    row(page, "a1").locator('[data-act="target"]').click()
    expect(page).to_have_url(re.compile(r"#/d/p1-kz-015$"))
    expect(page.locator('[data-view="d"]')).to_be_visible()
    assert api.errors == []


def test_alert_route_opens_its_why(page: Page, web_url: str) -> None:
    open_alerts(page, web_url, "#/alerts/a2")
    expect(row(page, "a2")).to_have_class(re.compile(r"\bsel\b"))
    expect(page.locator('[aria-label="Почему"]')).to_contain_text("Средний итог за 7 дней")


def test_operator_sees_why_but_no_alert_actions(page: Page, web_url: str) -> None:
    open_alerts(page, web_url)
    page.locator('[data-act="role"][data-role="operator"]').click()
    expect(page.locator('[data-act="ack"], [data-act="resolve"], [data-act="assign"]')).to_have_count(0)
    expect(row(page, "a1").locator('[data-act="why"]')).to_be_visible()
