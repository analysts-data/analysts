"""Панель «Интонация» в карточке звонка: ответ `/prosody` подменён, грузится при открытии карточки."""

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

PROSODY = {
    "lines": [
        {"n": 2, "f0": 118, "range_st": 6.1, "db": 66.0, "wps": 2.4, "pause": None, "flags": []},
        {"n": 3, "f0": 240, "range_st": 7.0, "db": 74.2, "wps": 2.1, "pause": 0.4, "flags": ["raised"]},
        {"n": 4, "f0": 120, "range_st": 5.3, "db": 65.1, "wps": 2.3, "pause": 9.4, "flags": ["long_pause"]},
        {"n": 7, "f0": 117, "range_st": 1.2, "db": 64.0, "wps": 2.2, "pause": 1.0, "flags": ["monotone"]},
        {
            "n": 8,
            "f0": 205,
            "range_st": 6.0,
            "db": 66.0,
            "wps": 4.6,
            "pause": 0.8,
            "flags": ["fast", "overlap"],
        },
    ],
    "speakers": {
        "client": {"f0": 200.0, "db": 66.0, "wps": 2.5, "lines": 4},
        "operator": {"f0": 118.0, "db": 65.0, "wps": 2.3, "lines": 6},
    },
    "summary": ["Клиент повысил тон в реплике 3", "Пауза 9 с перед ответом оператора (реплика 4)"],
}


def answer(page: Page, status: int, body: object) -> None:
    page.route(
        "**/api/dialogs/call-024/prosody",
        lambda r: r.fulfill(status=status, content_type="application/json", body=json.dumps(body)),
    )


def test_call_card_shows_intonation_summary_and_badges_next_to_lines(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    answer(page, 200, PROSODY)
    errors = open_card("call-024")

    panel = page.locator('[data-prosody="on"]')
    expect(panel).to_contain_text("Клиент повысил тон в реплике 3")
    expect(panel).to_contain_text("Пауза 9 с перед ответом оператора (реплика 4)")
    expect(page.locator('#tr [data-n="3"] .pros')).to_have_text(["↑ тон"])
    expect(page.locator('#tr [data-n="4"] .pros')).to_have_text(["пауза 9 с"])
    expect(page.locator('#tr [data-n="7"] .pros')).to_have_text(["монотонно"])
    expect(page.locator('#tr [data-n="8"] .pros')).to_have_text(["быстро", "перебивание"])
    expect(page.locator('#tr [data-n="2"] .pros')).to_have_count(0)
    assert errors == []


def test_chat_card_has_no_intonation_and_never_asks_for_it(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/prosody" in r.url else None)
    errors = open_card("p1-ru-003")

    expect(page.locator("[data-prosody]")).to_have_count(0)
    assert asked == []
    assert errors == []


def test_unavailable_record_leaves_a_muted_note_and_no_badges(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    answer(page, 502, {"detail": "Не удалось получить запись диалога call-024"})
    open_card("call-024")

    expect(page.locator('[data-prosody="off"]')).to_contain_text("Интонация недоступна")
    expect(page.locator('[data-prosody="on"]')).to_have_count(0)
    expect(page.locator(".pros")).to_have_count(0)


def test_call_without_record_hides_intonation(page: Page, open_card: Callable[..., list[str]]) -> None:
    answer(page, 404, {"detail": "У диалога call-024 нет записи"})
    with page.expect_response("**/api/dialogs/call-024/prosody"):
        open_card("call-024")

    expect(page.locator("[data-prosody]")).to_have_count(0)
