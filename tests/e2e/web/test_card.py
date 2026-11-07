import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_call_card_shows_total_sections_losses_and_points(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    errors = open_card("call-024")
    expect(page.locator(".ring")).to_contain_text("82,94")
    expect(page.locator(".secs")).to_contain_text("Безопасность и решение")
    expect(page.locator(".loss").nth(1)).to_contain_text("Реплика 30")
    expect(page.locator('.crit[data-cid="06"] .crit-row')).to_contain_text("10,5 / 15")
    assert errors == []


def test_open_criterion_shows_why_checked_segment_and_jumps_to_line(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    errors = open_card("call-024")
    page.click('.crit[data-cid="07"] [data-act="crit"]')
    body = page.locator('.crit[data-cid="07"] .crit-body')
    expect(body).to_contain_text("не подвёл итог и не попрощался")
    expect(body).to_contain_text("Проверен участок: реплики 30–32")
    body.locator('[data-act="ev"][data-n="30"]').click()
    line = page.locator('#tr [data-n="30"]')
    expect(line).to_be_in_viewport()
    expect(line).to_have_class(re.compile(r"\bflash\b"))
    assert errors == []


def test_hold_is_folded_until_shown(page: Page, open_card: Callable[..., list[str]]) -> None:
    def add_hold_lines(d: dict[str, Any]) -> None:
        lines = d["lines"]
        at = next(i for i, ln in enumerate(lines) if ln.get("fold")) + 1
        lines[at:at] = [
            {"n": 12, "t": 166.0, "s": 166.0, "who": "operator", "text": "Коллега, подскажи срок."},
            {"n": 13, "t": 200.0, "s": 200.0, "who": "operator", "text": "Понял, спасибо."},
        ]

    errors = open_card("call-024", add_hold_lines)
    fold = page.locator(".fold").first
    expect(fold).to_contain_text("Удержание и разговор с коллегой")
    expect(fold).to_contain_text("реплики 12–29")
    expect(fold).to_contain_text("не оценивается")
    expect(page.locator('#tr [data-n="12"]')).to_have_count(0)
    fold.get_by_role("button", name="Показать").click()
    expect(page.locator('#tr [data-n="12"]')).to_be_visible()
    expect(page.locator('#tr [data-n="13"]')).to_be_visible()
    assert errors == []


def test_na_criteria_show_their_condition_and_total_uses_applicable_only(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    errors = open_card("p1-ru-025")
    expect(page.locator(".ring")).to_contain_text("100,00")
    for cid, cond in (("04", "клиент сформулировал запрос"), ("07", "оборвался до возможности")):
        page.click(f'.crit[data-cid="{cid}"] [data-act="crit"]')
        expect(page.locator(f'.crit[data-cid="{cid}"] .box.na')).to_contain_text(cond)
    assert errors == []


def test_unknown_dialog_shows_message_and_link_back(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("unknown-id")
    expect(page.locator('[data-view="d"]')).to_contain_text("не найден")
    expect(page.locator('[data-view="d"] a[href="#/queue"]')).to_be_visible()
    assert errors == []
