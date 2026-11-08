"""Вставка диалога текстом: окно из очереди, карточка после сохранения и оценка одного диалога."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

STATE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"
TEXT = "Клиент: Здравствуйте, хочу подать заявку на карту\nОператор: Добрый день! Как вас зовут?"
TITLE = "Демо для жюри"

PASTED = {
    "id": "paste-1",
    "title": TITLE,
    "ch": "chat",
    "lang": "RU",
    "dur": None,
    "at": "08.11 12:00",
    "lines": [
        {
            "n": 1,
            "t": "00:00",
            "who": "client",
            "text": "Здравствуйте, хочу подать заявку на карту",
            "seg": "pre",
        },
        {"n": 2, "t": "00:01", "who": "operator", "text": "Добрый день! Как вас зовут?", "seg": "conv"},
    ],
    "res": {},
    "reviewed": False,
    "cost": None,
}
RUN_DONE = {
    "done": 1,
    "total": 1,
    "cost": 0.001,
    "calls": 8,
    "eta_s": 0,
    "errors": [],
    "status": "done",
}


def test_paste_saves_dialog_opens_card_and_offers_evaluation(page: Page, web_url: str) -> None:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    with_pasted = {**state, "dialogs": [PASTED, *state["dialogs"]]}
    loads = {"state": 0}

    def state_route(route) -> None:  # после сохранения reload видит вставленный диалог
        loads["state"] += 1
        body = with_pasted if loads["state"] > 1 else state
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/state", state_route)
    page.route(
        "**/api/dialogs/text",
        lambda r: r.fulfill(status=200, content_type="application/json", body='{"id": "paste-1"}'),
    )
    page.route(
        "**/api/runs",
        lambda r: r.fulfill(status=200, content_type="application/json", body='{"run_id": 1}'),
    )
    page.route(
        "**/api/runs/*",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(RUN_DONE)),
    )
    page.goto(f"{web_url}/#/queue")
    expect(page.get_by_text("Чек-лист v3", exact=True)).to_be_attached()

    page.get_by_role("button", name="Добавить диалоги").click()  # вставка — пункт меню
    page.locator('[data-act="paste"]').click()
    modal = page.locator("#dlgForm")
    expect(modal).to_be_visible()
    expect(modal.locator('[data-act="psave"]')).to_be_disabled()
    modal.locator('[name="title"]').fill(TITLE)
    modal.locator('[name="text"]').fill(TEXT)
    expect(modal.locator('[data-act="psave"]')).to_be_enabled()
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/dialogs/text")) as req:
        modal.locator('[data-act="psave"]').click()
    assert req.value.post_data_json == {"title": TITLE, "ch": "chat", "text": TEXT}

    expect(page).to_have_url(re.compile(r"#/d/paste-1$"))  # карточка открылась
    expect(page.locator('[data-view="d"] h1')).to_have_text(TITLE)
    expect(page.locator('[data-act="open"][data-id="paste-1"]')).to_have_count(
        0
    )  # очередь не на экране карточки
    page.evaluate("location.hash = '#/queue'")
    expect(page.locator('[data-act="open"][data-id="paste-1"]')).to_be_visible()  # диалог появился в очереди
    page.evaluate("location.hash = '#/d/paste-1'")

    expect(page.locator('#dlgForm [data-act="prun"]')).to_be_visible()
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/runs")) as run_req:
        page.locator('[data-act="prun"]').click()
    assert run_req.value.post_data_json == {"dialogs": ["paste-1"], "criteria": None}
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.evaluate("location.hash = '#/queue'")
    expect(page.locator("#runProgress")).to_contain_text("оценено 1 из 1")  # опрос дошёл до done
    assert problems == []


def test_paste_without_operator_line_shows_server_error_in_the_modal(page: Page, web_url: str) -> None:
    page.route(
        "**/api/state",
        lambda r: r.fulfill(
            status=200, content_type="application/json", body=STATE_PATH.read_text(encoding="utf-8")
        ),
    )
    page.route(
        "**/api/dialogs/text",
        lambda r: r.fulfill(
            status=422,
            content_type="application/json",
            body=json.dumps({"detail": "в диалоге нет реплики оператора"}),
        ),
    )
    page.goto(f"{web_url}/#/queue")
    page.get_by_role("button", name="Добавить диалоги").click()  # вставка — пункт меню
    page.locator('[data-act="paste"]').click()
    modal = page.locator("#dlgForm")
    modal.locator('[name="title"]').fill(TITLE)
    modal.locator('[name="text"]').fill("Клиент: один на свете")
    modal.locator('[data-act="psave"]').click()
    expect(modal.locator("#pErr")).to_have_text("Диалог не сохранён: 422: в диалоге нет реплики оператора")
    expect(page.get_by_role("dialog")).to_be_visible()  # окно осталось открытым
