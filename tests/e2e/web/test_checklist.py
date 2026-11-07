from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)


def open_checklist(page: Page, web_url: str) -> None:
    page.route(
        "**/api/state", lambda route: route.fulfill(status=200, content_type="application/json", body=STATE)
    )
    page.goto(f"{web_url}/#/checklist")
    expect(page.locator('[data-view="checklist"] h1')).to_have_text("Чек-лист качества")


def item(page: Page, cid: str) -> Locator:
    return page.locator(f'[data-view="checklist"] [data-act="csel"][data-cid="{cid}"]')


def test_weight_change_shows_sum_and_changed_mark_and_reset_restores(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    expect(page.get_by_text("Сумма весов 100")).to_be_visible()
    item(page, "04").click()
    page.locator("#cf-w").fill("25")
    page.locator("#cf-w").press("Tab")
    expect(page.get_by_text("Сумма весов 105")).to_be_visible()
    expect(page.get_by_text("Итог всё равно приводится к 100")).to_be_visible()
    expect(item(page, "04")).to_contain_text("изменён")
    expect(item(page, "03")).not_to_contain_text("изменён")
    page.locator('[data-act="creset"]').click()
    expect(page.get_by_text("Сумма весов 100")).to_be_visible()
    expect(item(page, "04")).not_to_contain_text("изменён")


def test_type_change_rebuilds_fields(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    item(page, "01").click()
    expect(page.locator("#cf-steps")).to_have_count(0)
    page.locator("#cf-type").select_option("scale")
    expect(page.locator("#cf-steps")).to_have_value("10: Полностью\n5: Частично\n0: Нет")
    expect(page.locator("#cf-w")).to_be_visible()
    page.locator("#cf-type").select_option("flag")
    expect(page.locator("#cf-w")).to_have_count(0)
    expect(page.locator("#cf-steps")).to_have_count(0)
    expect(page.locator("#cf-q")).to_be_visible()


def test_add_and_delete_criterion(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    page.locator('[data-act="cadd"]').click()
    expect(item(page, "09")).to_contain_text("изменён")
    expect(page.locator('[data-view="checklist"] legend')).to_contain_text("Критерий 09")
    expect(page.locator("#cf-type")).to_have_value("bool")
    expect(page.locator("#cf-sec")).to_have_value("2")
    expect(page.locator("#cf-w")).to_have_value("5")
    expect(page.locator("#cf-na")).not_to_be_checked()
    expect(page.locator("#cf-ch")).to_have_value("all")
    expect(page.get_by_text("Сумма весов 105")).to_be_visible()
    page.locator('[data-act="cdel"]').click()
    expect(item(page, "09")).to_have_count(0)
    expect(page.get_by_text("Сумма весов 100")).to_be_visible()
