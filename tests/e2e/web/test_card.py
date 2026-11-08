import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
STATE = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"


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


def open_crit(page: Page, cid: str) -> None:
    if page.locator(f'.crit[data-cid="{cid}"] .crit-body').count() == 0:
        page.click(f'.crit[data-cid="{cid}"] [data-act="crit"]')


def state_with(review: dict[str, Any]) -> str:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    state["appeals"].append(review)
    return json.dumps(state)


def review_of(dlg: str, cid: str, frm: Any, to: Any, reason: str) -> dict[str, Any]:
    return {
        "id": "a9", "kind": "review", "dlg": dlg, "cid": cid, "from": frm, "to": to, "ev": [],
        "by": "Специалист КК", "at": "07.11 16:00", "status": "changed" if to != frm else "confirmed",
        "comment": None, "reviewer": "Специалист КК", "reason": reason, "decidedAt": "07.11 16:00",
    }  # fmt: skip


def test_accepting_second_opinion_posts_review_decision(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    errors = open_card("p1-en-008")
    open_crit(page, "07")
    block = page.locator('.crit[data-cid="07"] .box.info')
    expect(block).to_contain_text("Второе мнение: Да")
    reason = "Оператор ответил на второй вопрос и попрощался."
    after = state_with(review_of("p1-en-008", "07", "no", "yes", reason))
    page.route(
        "**/api/decisions", lambda r: r.fulfill(status=200, content_type="application/json", body="{}")
    )
    block.get_by_role("button", name="Принять Да").click()
    page.fill('#dlg textarea[name="reason"]', reason)
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=after))
    with page.expect_request("**/api/decisions") as request:
        page.click('#dlg button[value="ok"]')
    assert request.value.post_data_json == {
        "dlg": "p1-en-008", "cid": "07", "from": "no", "to": "yes",
        "reason": reason, "reviewer": "Специалист КК",
    }  # fmt: skip
    expect(block).to_have_count(0)
    assert errors == []


def test_failed_quote_asks_for_check(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("p1-kz-003")
    open_crit(page, "06")
    body = page.locator('.crit[data-cid="06"] .crit-body')
    expect(body.locator(".box.ev")).to_contain_text("Цитата не нашлась")
    expect(body).to_contain_text("на проверку")
    expect(body.locator('[data-act="review"]')).to_have_count(2)
    assert errors == []


def test_reduced_criterion_shows_better_phrase_and_review_history(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    def add_better(d: dict[str, Any]) -> None:
        d["res"]["06"]["better"] = "Уточню у коллег, это займёт около трёх минут."

    errors = open_card("call-024", add_better)
    open_crit(page, "06")
    expect(page.locator('.crit[data-cid="06"] .box.good')).to_contain_text("Как сказать лучше")
    after = state_with(review_of("call-024", "04", 15, 10, "Срок ответа не назван."))
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=after))
    page.evaluate("() => import('./js/state.js').then(s => s.reload())")
    open_crit(page, "04")
    history = page.locator('.crit[data-cid="04"] .hist')
    expect(history).to_contain_text("Решение")
    expect(history).to_contain_text("Срок ответа не назван.")
    expect(page.locator('.crit[data-cid="04"] .box.info')).to_have_count(0)
    assert errors == []


def test_cost_line_comes_from_dialog_cost(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("p1-ru-003")
    meta = page.locator(".meta")
    for text in ("qwen3-6", "10 вызовов", "1 запрос второго мнения", "$0,01", "41 с"):
        expect(meta).to_contain_text(text)
    assert errors == []


def test_cost_line_without_evaluation(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("p1-en-006")
    expect(page.locator(".meta")).to_contain_text("ещё не оценивался")
    assert errors == []


FLAG_WHY = (
    "Оскорбление клиента: Грубых слов нет; "
    "Платная услуга в обход компании: Предложил консультацию за плату; через личный номер (реплики 6); "
    "Раскрытие конфиденциальной информации: Назвал данные счёта (реплики 4, 8)"
)


def test_flag_shows_reason_and_evidence_lines_per_question(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    def two_flags(d: dict[str, Any]) -> None:
        d["res"]["08"].update(a={"insult": False, "paid": True, "leak": True}, ev=[4, 6, 8], why=FLAG_WHY)

    errors = open_card("p1-ru-022", two_flags)
    open_crit(page, "08")
    body = page.locator('.crit[data-cid="08"] .crit-body')
    paid, leak, insult = (body.locator(f'[data-k="{k}"]') for k in ("paid", "leak", "insult"))
    expect(paid).to_contain_text("Предложил консультацию за плату; через личный номер")
    expect(paid.locator('[data-act="ev"]')).to_have_count(1)
    expect(paid.locator('[data-act="ev"][data-n="6"]')).to_be_visible()
    expect(leak).to_contain_text("Назвал данные счёта")
    expect(leak.locator('[data-act="ev"]')).to_have_count(2)
    expect(insult).to_contain_text("Грубых слов нет")
    expect(insult.locator('[data-act="ev"]')).to_have_count(0)
    expect(body).not_to_contain_text("(реплики")
    expect(body.locator('[data-act="appeal"][data-cid="08"]')).to_be_visible()
    assert errors == []


def test_expand_all_opens_every_reason_and_collapse_closes_them(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    errors = open_card("p1-ru-022")
    toggle = page.locator('[data-act="critall"]')
    expect(toggle).to_have_text("Развернуть все обоснования")
    toggle.click()
    expect(page.locator(".crit-body")).to_have_count(page.locator(".crit").count())
    expect(toggle).to_have_text("Свернуть")
    toggle.click()
    expect(page.locator(".crit-body")).to_have_count(0)
    expect(toggle).to_have_text("Развернуть все обоснования")
    assert errors == []


def test_scale_below_max_without_evidence_shows_checked_segment(
    page: Page, open_card: Callable[..., list[str]]
) -> None:
    def segment(d: dict[str, Any]) -> None:
        d["res"]["06"].update(ev=[], seg="реплики 4–8")  # 4 из 10

    errors = open_card("p1-ru-003", segment)
    open_crit(page, "06")
    expect(page.locator('.crit[data-cid="06"] .crit-body')).to_contain_text("Проверен участок: реплики 4–8")
    assert errors == []
