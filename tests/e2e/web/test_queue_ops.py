"""Очередь для большой команды: оператор, продукт, маркеры, «оценивается», «Оценить заново», выгрузка CSV.

Ответы новых эндпоинтов — по черновику контракта (openspec/changes/react-frontend/helpers-ops.md).
"""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e

STATE: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(encoding="utf-8")
)
CARDS = {"id": "cards", "name": "Карты", "confidence": 0.92, "by": "model"}
CREDIT = {"id": "credit", "name": "Кредиты", "confidence": None, "by": "qa"}
OPS = {
    "p1-kz-015": {
        "operator": "Алия К.",
        "product": CARDS,
        "markers": [{"k": "vip", "label": "VIP-клиент", "auto": False}],
    },
    "p1-ru-009": {
        "operator": "Борис Н.",
        "product": CREDIT,
        "markers": [
            {"k": "churn", "label": "Риск ухода", "auto": True, "basis": {"rule": "клиент назвал конкурента"}}
        ],
    },
    "call-024": {"operator": "Алия К.", "product": CARDS, "markers": []},
}
# Новые эндпоинты: очередь не должна звать их при загрузке (статический сервер и старый сервер их не знают).
NEW_ON_LOAD = re.compile(
    r"/api/(runs|scores|operators|products|markers|overview|audit|reports|usage|dialogs/[^/]+/history)"
)


def state_with_ops() -> dict[str, Any]:
    state = copy.deepcopy(STATE)
    for d in state["dialogs"]:
        d.update(copy.deepcopy(OPS.get(d["id"], {})))
    return state


def open_queue(page: Page, web_url: str, state: dict[str, Any], route: str = "#/queue") -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/state", lambda r: r.fulfill(json=state))
    page.goto(f"{web_url}/{route}")
    expect(page.locator('[data-act="open"]').first).to_be_visible()
    return errors


def row_ids(page: Page) -> list[str]:
    return [el.get_attribute("data-id") or "" for el in page.locator('[data-act="open"]').all()]


def test_queue_without_ops_data_hides_new_filters_and_calls_no_new_endpoint(page: Page, web_url: str) -> None:
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    errors = open_queue(page, web_url, STATE)
    expect(page.locator('[data-act="open"]')).to_have_count(10)
    for sel in ("#fop", "#fprod", "#fmk", ".mark"):
        expect(page.locator(sel)).to_have_count(0)
    expect(page.locator("th", has_text="Оператор")).to_have_count(0)
    page.wait_for_timeout(300)
    assert [u for u in urls if NEW_ON_LOAD.search(u)] == []
    assert errors == []


def test_operator_column_and_filter_keep_queue_order(page: Page, web_url: str) -> None:
    errors = open_queue(page, web_url, state_with_ops())
    expect(page.locator("th", has_text="Оператор")).to_be_visible()
    expect(page.locator('[data-act="open"][data-id="p1-kz-015"]')).to_contain_text("Алия К.")
    expect(page.locator('[data-act="open"][data-id="p1-en-006"]')).to_contain_text("Не указан")
    page.locator("#fop").select_option("Алия К.")
    expect(page).to_have_url(re.compile(r"#/queue\?op=%D0%90"))
    expect(page.locator('[data-act="open"]')).to_have_count(2)
    assert row_ids(page) == ["p1-kz-015", "call-024"]
    page.locator("#fop").select_option("Не указан")
    expect(page.locator('[data-act="open"]')).to_have_count(7)
    page.locator('[data-act="clear"]').click()
    expect(page.locator('[data-act="open"]')).to_have_count(10)
    assert errors == []


def test_product_and_marker_filters_and_marker_chips(page: Page, web_url: str) -> None:
    open_queue(page, web_url, state_with_ops())
    expect(page.locator('[data-act="open"][data-id="p1-ru-009"] .mark')).to_have_text("Риск ухода")
    expect(page.locator('[data-act="open"][data-id="p1-ru-009"]')).to_contain_text("Кредиты")
    page.locator("#fprod").select_option("Карты")
    expect(page).to_have_url(re.compile(r"prod=cards"))
    expect(page.locator('[data-act="open"]')).to_have_count(2)
    assert row_ids(page) == ["p1-kz-015", "call-024"]
    page.locator("#fprod").select_option("")
    page.locator("#fmk").select_option("Риск ухода")
    expect(page).to_have_url(re.compile(r"mk=churn"))
    expect(page.locator('[data-act="open"]')).to_have_count(1)
    assert row_ids(page) == ["p1-ru-009"]


class Runs:
    """POST /api/runs и GET /api/runs/{id}: прогресс отдаёт `progress`, запросы копятся в `posts`."""

    def __init__(self, page: Page, progress: dict[str, Any]) -> None:
        self.posts: list[Any] = []
        self.progress = progress
        page.route("**/api/runs", self.post)
        page.route("**/api/runs/*", lambda r: r.fulfill(json=self.progress))

    def post(self, route: Route) -> None:
        self.posts.append(route.request.post_data_json)
        route.fulfill(json={"run_id": 7})


RUNNING = {
    "done": 4,
    "total": 80,
    "cost": 0.0,
    "calls": 4,
    "eta_s": 30,
    "errors": [],
    "status": "running",
    "skipped": 3,
}


def test_rerun_whole_set_asks_confirmation_then_posts_force(page: Page, web_url: str) -> None:
    errors = open_queue(page, web_url, STATE)
    runs = Runs(page, RUNNING)
    page.locator('[data-act="rerun"]').click()
    dialog = page.get_by_role("dialog", name="Оценить заново весь набор?")
    expect(dialog).to_contain_text("Ручные ответы специалиста и ответы с апелляцией не перезапишутся")
    assert runs.posts == []  # без подтверждения ничего не ушло
    dialog.locator('[data-act="rerun-all"]').click()
    panel = page.get_by_role("region", name="Оценка набора")
    expect(panel).to_contain_text("Идёт оценка")
    expect(panel).to_contain_text("Не перезаписаны ручные ответы и ответы с апелляцией: 3")
    assert runs.posts == [{"dialogs": None, "criteria": None, "force": True}]
    expect(panel.locator('[data-act="stop"]')).to_be_visible()
    assert errors == []


def test_rerun_shown_dialogs_posts_force_without_confirmation_and_marks_rows(
    page: Page, web_url: str
) -> None:
    open_queue(page, web_url, STATE, "#/queue?ch=call")
    runs = Runs(page, RUNNING)
    page.get_by_role("button", name="Оценить заново показанные: 1").click()
    expect(page.locator('[data-act="open"][data-id="call-024"]')).to_contain_text("Оценивается…")
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert runs.posts == [{"dialogs": ["call-024"], "criteria": None, "force": True}]


def test_rows_say_being_scored_from_run_dialog_states(page: Page, web_url: str) -> None:
    open_queue(page, web_url, STATE)
    Runs(page, {**RUNNING, "dialogs": {"p1-ru-009": "running", "p1-ru-022": "queued", "p1-kz-015": "done"}})
    page.locator('[data-act="run"]').click()
    expect(page.locator('[data-act="open"][data-id="p1-ru-009"]')).to_contain_text("Оценивается…")
    expect(page.locator('[data-act="open"][data-id="p1-ru-022"]')).to_contain_text("Оценивается…")
    expect(page.locator('[data-act="open"][data-id="p1-kz-015"]')).not_to_contain_text("Оценивается")


def test_export_downloads_scores_csv_with_queue_filters(page: Page, web_url: str) -> None:
    open_queue(page, web_url, STATE, "#/queue?lang=KZ")
    asked: list[str] = []

    def export(route: Route) -> None:
        asked.append(route.request.url)
        route.fulfill(
            body="﻿ID;Итог\np1-kz-015;77,06\n",
            headers={
                "Content-Type": "text/csv; charset=utf-8",
                "Content-Disposition": 'attachment; filename="cqa-scores-v3.csv"',
            },
        )

    page.route("**/api/scores/export*", export)
    with page.expect_download() as dl:
        page.get_by_role("button", name="Выгрузить оценки (CSV)").click()
    assert dl.value.suggested_filename == "cqa-scores-v3.csv"
    assert len(asked) == 1 and "format=csv" in asked[0] and "shape=wide" in asked[0] and "lang=KZ" in asked[0]
    expect(page.get_by_role("button", name="Выгрузить оценки (CSV)")).to_be_enabled()
