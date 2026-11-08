"""Ручная оценка, запуск модели из карточки и окно режима оценки: что уходит на сервер по кнопкам."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
CONFIG = {
    "llm_mode": "live",
    "llm_base_url": "https://llm.alem.ai/v1",
    "llm_model": "qwen3-6",
    "llm_profile": "plain",
    "profiles": ["plain", "deepseek"],
    "has_llm_key": True,
    "data_where": "kz",
    "anonymize": True,
    "verifier": None,
    "has_jev_key": False,
    "allow_real_data": False,
}


def _open_mode(page: Page) -> None:
    page.click("#mode")
    expect(page.locator("#dlg[open] #dlgTitle")).to_have_text("Режим оценки")  # форма из GET /api/config


def _capture(page: Page, pattern: str, answer: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def handle(route: Route) -> None:
        if route.request.method in ("PUT", "POST"):
            sent.append(json.loads(route.request.post_data or "null"))
        route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    page.route(pattern, handle)
    return sent


def test_pending_criterion_is_scored_by_hand(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("call-024", lambda d: d["res"].pop("01"))
    sent = _capture(page, "**/api/dialogs/call-024/answers/01", {"a": "no"})
    page.click('.crit[data-cid="01"] [data-act="crit"]')
    page.click('.crit[data-cid="01"] [data-act="manual"]')
    page.select_option('#dlgForm select[name="a"]', "no")
    page.fill('#dlgForm textarea[name="reason"]', "Не представился")
    page.click('#dlgForm button[value="ok"]')
    expect(page.locator("#toast")).to_contain_text("Ответ сохранён")
    assert sent == [{"a": "no", "reason": "Не представился", "by": "Специалист КК"}]
    assert errors == []


def test_model_answer_can_be_changed_by_hand(page: Page, open_card: Callable[..., list[str]]) -> None:
    open_card("call-024")
    sent = _capture(page, "**/api/dialogs/call-024/answers/06", {"a": 15})
    page.click('.crit[data-cid="06"] [data-act="crit"]')
    page.click('.crit[data-cid="06"] [data-act="manual"]')
    page.select_option('#dlgForm select[name="a"]', "10")
    page.click('#dlgForm button[value="ok"]')
    expect(page.locator("#toast")).to_contain_text("Ответ сохранён")
    assert sent == [{"a": 10, "reason": "", "by": "Специалист КК"}]


def test_card_runs_the_model_on_its_pending_criteria(page: Page, open_card: Callable[..., list[str]]) -> None:
    open_card("call-024", lambda d: d["res"].pop("01"))
    sent = _capture(page, "**/api/runs", {"run_id": 7})
    page.route(
        "**/api/runs/7",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"done": 1, "total": 1, "cost": 0, "calls": 1, "eta_s": 0, "errors": [], "status": "done"}
            ),
        ),
    )
    page.click('[data-act="evalone"]')
    expect(page.locator("#toast")).to_contain_text("запущена")
    assert sent == [{"dialogs": ["call-024"], "criteria": None}]


def test_mode_badge_opens_the_mode_and_saves_a_local_model(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    open_card("call-024")
    sent = _capture(page, "**/api/config", CONFIG)
    _open_mode(page)
    page.check('#dlgForm input[name="preset"][value="local"]')
    page.fill('#dlgForm input[name="llm_base_url"]', "http://10.0.0.5:11434/v1")
    page.fill('#dlgForm input[name="llm_model"]', "qwen3:32b")
    page.click('#dlgForm button[value="ok"]')
    expect(page.locator("#toast")).to_contain_text("Режим сохранён")
    assert sent == [
        {
            "llm_base_url": "http://10.0.0.5:11434/v1",
            "llm_model": "qwen3:32b",
            "llm_profile": "plain",
            "llm_api_key": "",
            "data_where": "local",
            "anonymize": False,
            "verifier": None,
            "jev_api_key": "",
            "allow_real_data": False,
        }
    ]


def test_raw_text_abroad_needs_a_confirmation(page: Page, open_card: Callable[..., list[str]]) -> None:
    open_card("call-024")
    sent = _capture(page, "**/api/config", CONFIG)
    _open_mode(page)
    page.check('#dlgForm input[name="preset"][value="raw"]')
    page.select_option('#dlgForm select[name="where"]', "external")
    page.check('#dlgForm input[name="jev"]')
    page.fill('#dlgForm input[name="jev_api_key"]', "jev-key")
    page.once("dialog", lambda d: d.dismiss())
    page.click('#dlgForm button[value="ok"]')
    page.wait_for_timeout(200)
    assert sent == []
    _open_mode(page)
    page.check('#dlgForm input[name="preset"][value="raw"]')
    page.once("dialog", lambda d: d.accept())
    page.click('#dlgForm button[value="ok"]')
    expect(page.locator("#toast")).to_contain_text("Режим сохранён")
    assert (sent[0]["anonymize"], sent[0]["data_where"]) == (False, "kz")
