"""Перепроверка «Только сравнить» → сравнение → «Сделать текущим» и «Принять все»; чипы достаточности данных.

Эндпоинты сервера подставляет `page.route` по контракту перепроверки (POST /api/runs с apply и override,
GET /api/dialogs/{id}/history со строками shadow, POST /api/runs/{id}/adopt) и полю Dialog.sufficiency.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"
CARD = "call-024"


def json_reply(route: Route, body: object) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def serve(page: Page, edit: Any = None) -> list[str]:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if edit:
        edit(state)
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/state", lambda r: json_reply(r, state))
    return errors


def row(
    rid: int, a: Any, model: str, *, run: int, shadow: bool = False, current: bool = False
) -> dict[str, Any]:
    return {"id": rid, "created": "2026-11-08T07:00:00", "run_id": run, "version": 2, "model": model, "a": a,
            "why": f"Обоснование {rid}", "ev": [], "current": current, "stale": False, "shadow": shadow}  # fmt: skip  # noqa: E501


def test_recheck_compare_then_restore_one_and_adopt_all(page: Page, web_url: str) -> None:
    errors = serve(page)
    sent: dict[str, list[Any]] = {"run": [], "restore": [], "adopt": []}
    history = {
        "07": [row(91, "yes", "gpt-x", run=7, shadow=True), row(50, "no", "qwen3-6", run=3, current=True)],
        "01": [row(92, "yes", "gpt-x", run=7, shadow=True), row(51, "yes", "qwen3-6", run=3, current=True)],
    }

    def post_run(route: Route) -> None:
        sent["run"].append(route.request.post_data_json)
        json_reply(route, {"run_id": 7})

    page.route(re.compile(r".*/api/runs$"), post_run)
    page.route("**/api/runs/7", lambda r: json_reply(r, {
        "done": 2, "total": 2, "cost": 0.0, "calls": 2, "eta_s": None, "errors": [], "status": "done", "skipped": 1,  # noqa: E501
        "dialogs": [{"id": CARD, "status": "done"}],
    }))  # fmt: skip
    page.route(f"**/api/dialogs/{CARD}/history", lambda r: json_reply(r, history))
    page.route(
        "**/api/results/92/restore", lambda r: (sent["restore"].append(r.request.url), json_reply(r, {}))[1]
    )
    page.route("**/api/runs/7/adopt", lambda r: (sent["adopt"].append(r.request.post_data_json), json_reply(r, {"adopted": 1, "skipped": 0}))[1])  # fmt: skip  # noqa: E501

    page.goto(f"{web_url}/#/d/{CARD}")
    page.locator('[data-act="recheck"]:not([data-cid])').click()
    expect(page.locator('[data-apply="compare"]')).to_have_attribute("aria-checked", "true")
    page.locator('[data-act="recheck-same"]').click()

    cmp = page.locator('[data-compare="7"]')
    expect(cmp.locator('tr[data-cid="07"]')).to_have_attribute("data-changed", "true")
    expect(cmp.locator('tr[data-cid="07"]')).to_contain_text("gpt-x")
    expect(cmp.locator('tr[data-cid="01"]')).to_have_attribute("data-changed", "false")
    expect(cmp.locator('[data-compare="skipped"]')).to_have_text("Пропущено: 1 (ручные ответы и решения).")
    expect(cmp.locator('[data-compare="total"]')).to_contain_text("→")
    assert sent["run"] == [{"dialogs": [CARD], "criteria": None, "force": True, "apply": "compare"}]

    cmp.locator('[data-act="cmp-restore"][data-rid="92"]').click()
    expect(cmp.locator('tr[data-cid="01"]')).to_contain_text("текущая")
    cmp.locator('[data-act="cmp-adopt"]').click()
    expect(page.locator("#toast")).to_contain_text("Принято ответов: 1, пропущено: 0.")
    expect(cmp.locator('[data-act="cmp-adopt"]')).to_be_disabled()
    assert len(sent["restore"]) == 1
    assert sent["adopt"] == [{"dialogs": [CARD]}]
    assert errors == []


def test_sufficiency_chips_in_queue_and_card_open_reasons(page: Page, web_url: str) -> None:
    reason = {
        "id": "no_operator",
        "text": "Нет реплик оператора",
        "basis": "Оценивать нечего",
        "outcome": "block",
    }

    def edit(state: dict[str, Any]) -> None:
        ds = {d["id"]: d for d in state["dialogs"]}
        ds[CARD]["sufficiency"] = {"status": "block", "reasons": [reason]}
        ds["p1-ru-022"]["sufficiency"] = {"status": "flag", "reasons": [{**reason, "id": "too_short", "text": "Слишком короткий диалог", "outcome": "flag"}]}  # fmt: skip  # noqa: E501
        ds["p1-ru-025"]["sufficiency"] = {"status": "ok", "reasons": []}

    errors = serve(page, edit)
    page.goto(f"{web_url}/#/queue")
    chips = page.locator('[data-act="sufficiency"]')
    expect(chips).to_have_count(2)
    expect(page.locator(f'tr[data-id="{CARD}"] [data-act="sufficiency"]')).to_have_text("Недостаточно данных")
    expect(page.locator('tr[data-id="p1-ru-022"] [data-act="sufficiency"]')).to_have_text("Мало данных")

    page.locator(f'tr[data-id="{CARD}"] [data-act="sufficiency"]').click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Нет реплик оператора")
    expect(dialog).to_contain_text("Оценивать нечего")
    page.keyboard.press("Escape")
    expect(page).to_have_url(re.compile(r"#/queue"))  # клик по чипу не открывает карточку

    page.goto(f"{web_url}/#/d/{CARD}")
    expect(page.locator('[data-view="d"] [data-act="sufficiency"]')).to_have_text("Недостаточно данных")
    assert errors == []
