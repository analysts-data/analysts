import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

STATE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"

# Порядок очереди на фикстуре прототипа: группы risk → review → next → other,
# внутри группы итог по возрастанию.
QUEUE_ORDER = [
    "p1-kz-015",
    "p1-ru-009",
    "p1-ru-022",
    "call-024",
    "p1-kz-003",
    "p1-en-008",
    "p1-ru-003",
    "p1-ru-029",
    "p1-ru-025",
    "p1-en-006",
]


def open_queue(page: Page, web_url: str, route: str = "#/queue") -> None:
    state = STATE_PATH.read_text(encoding="utf-8")
    page.route(
        "**/api/state",
        lambda route_: route_.fulfill(status=200, content_type="application/json", body=state),
    )
    page.goto(f"{web_url}/{route}")
    expect(page.locator("#clVer")).to_have_text("Чек-лист v3")


def row_ids(page: Page) -> list[str]:
    return [el.get_attribute("data-id") for el in page.locator('[data-act="open"]').all()]


def test_queue_lists_dialogs_by_group_and_total(page: Page, web_url: str) -> None:
    open_queue(page, web_url)
    rows = page.locator('[data-act="open"]')
    expect(rows).to_have_count(10)
    assert row_ids(page) == QUEUE_ORDER
    headers = page.locator("tr.grp .chip").all_inner_texts()
    assert headers == [
        "Грубые ошибки: 3",
        "Нужна проверка человека: 3",
        "Без понятного следующего шага: 1",
        "Остальные: 3",
    ]


def test_risk_tile_filters_and_reset_returns_full_list(page: Page, web_url: str) -> None:
    open_queue(page, web_url)
    page.locator('[data-act="grp"][data-g="risk"]').click()
    expect(page).to_have_url(re.compile(r"#/queue\?grp=risk$"))
    rows = page.locator('[data-act="open"]')
    expect(rows).to_have_count(3)
    assert row_ids(page) == ["p1-kz-015", "p1-ru-009", "p1-ru-022"]
    page.locator('[data-act="clear"]').click()
    expect(page).to_have_url(re.compile(r"#/queue$"))
    expect(page.locator('[data-act="open"]')).to_have_count(10)


def test_j_j_enter_opens_third_dialog_in_queue_order(page: Page, web_url: str) -> None:
    open_queue(page, web_url)
    page.keyboard.press("j")
    page.keyboard.press("j")
    expect(page.locator("tr.sel")).to_have_count(1)
    assert page.locator("tr.sel").get_attribute("data-id") == "p1-ru-022"
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"#/d/p1-ru-022$"))
    expect(page.locator('[data-view="d"]')).to_be_visible()


def test_k_at_first_row_keeps_selection(page: Page, web_url: str) -> None:
    open_queue(page, web_url)
    page.keyboard.press("k")
    assert page.locator("tr.sel").get_attribute("data-id") == "p1-kz-015"


def test_j_k_in_card_follow_queue_order(page: Page, web_url: str) -> None:
    open_queue(page, web_url, "#/d/call-024")
    page.keyboard.press("j")
    expect(page).to_have_url(re.compile(r"#/d/p1-kz-003$"))
    page.keyboard.press("k")
    expect(page).to_have_url(re.compile(r"#/d/call-024$"))


def test_lost_and_lang_filters_come_from_hash(page: Page, web_url: str) -> None:
    open_queue(page, web_url, "#/queue?lost=07&lang=KZ")
    rows = page.locator('[data-act="open"]')
    expect(rows).to_have_count(1)
    assert rows.first.get_attribute("data-id") == "p1-kz-015"


def test_search_filters_rows_without_changing_hash(page: Page, web_url: str) -> None:
    open_queue(page, web_url)
    page.fill("#q", "подал заявку")
    rows = page.locator('[data-act="open"]')
    expect(rows).to_have_count(1)
    assert rows.first.get_attribute("data-id") == "p1-ru-003"
    assert page.evaluate("location.hash") == "#/queue"


def test_evaluate_posts_visible_dialogs_in_queue_order(page: Page, web_url: str) -> None:
    open_queue(page, web_url, "#/queue?ch=call")
    page.route(
        "**/api/runs",
        lambda route_: route_.fulfill(
            status=200, content_type="application/json", body=json.dumps({"run_id": 1})
        ),
    )
    page.route(
        "**/api/runs/*",
        lambda route_: route_.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "done": 1,
                    "total": 1,
                    "cost": 0.0,
                    "calls": 8,
                    "eta_s": 0,
                    "errors": [],
                    "status": "done",
                }
            ),
        ),
    )
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/runs")) as req:
        page.locator('[data-act="run"]').click()
    assert req.value.post_data_json == {"dialogs": ["call-024"], "criteria": None}
