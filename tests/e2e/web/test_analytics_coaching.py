import json
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "analytics_state.json").read_text(
    encoding="utf-8"
)


def open_page(page: Page, web_url: str, route: str) -> list[str]:
    """Отдаёт фикстуру на GET /api/state и возвращает журнал запросов к /api/."""
    requests: list[str] = []
    page.on(
        "request",
        lambda r: requests.append(f"{r.method} {r.url.split('/api', 1)[1]}") if "/api/" in r.url else None,
    )
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.goto(f"{web_url}/{route}")
    return requests


def test_analytics_tiles_and_tables_from_state_only(page: Page, web_url: str) -> None:
    requests = open_page(page, web_url, "#/analytics")
    expect(page.locator(".lens a strong")).to_have_text(["1", "4", "56%", "5"])
    expect(page.locator('[aria-label="Результат по критериям"] tbody tr')).to_have_count(7)
    expect(page.locator('[aria-label="Критерий и язык"] tbody tr')).to_have_count(7)
    expect(page.locator('[aria-label="Повторяющиеся причины"] tbody tr')).to_have_count(4)
    expect(page.locator('a[href="#/queue?lost=07&lang=KZ"]')).to_have_text("1 из 2")
    assert requests == ["GET /state"]


def test_owner_change_puts_and_shows_server_answer(page: Page, web_url: str) -> None:
    bodies: list[object] = []

    def owners(route: Route) -> None:
        bodies.append(json.loads(route.request.post_data or "null"))
        answer = {"Не назван срок ответа": "Сервис", "Грубый тон": "Инструкция"}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    page.route("**/api/owners", owners)
    open_page(page, web_url, "#/analytics")
    select = page.locator('select[data-tag="Не назван срок ответа"]')
    select.select_option("Сервис")
    expect(page.locator('select[data-tag="Не назван срок ответа"]')).to_have_value("Сервис")
    assert bodies == [{"Не назван срок ответа": "Сервис"}]


def test_owner_change_rejected_restores_previous_value(page: Page, web_url: str) -> None:
    page.route("**/api/owners", lambda r: r.fulfill(status=500, body='{"detail": "база недоступна"}'))
    open_page(page, web_url, "#/analytics")
    page.locator('select[data-tag="Не назван срок ответа"]').select_option("Сервис")
    expect(page.locator("#toast")).to_contain_text("база недоступна")
    expect(page.locator('select[data-tag="Не назван срок ответа"]')).to_have_value("Инструкция")


@pytest.mark.xfail(reason="фильтры очереди и карточка — cqa-web-ui, группы 4 и 5", strict=False)
def test_three_clicks_from_number_to_reasoning(page: Page, web_url: str) -> None:
    open_page(page, web_url, "#/analytics")
    page.click('a[href="#/queue?lost=07&lang=KZ"]')
    expect(page.locator('[data-act="open"]')).to_have_count(1)
    page.click('[data-act="open"][data-id="p1-kz-015"]')
    expect(page).to_have_url(f"{page.url.split('#')[0]}#/d/p1-kz-015")
    page.click('[data-cid="07"] .crit-row')
    expect(page.locator('[data-cid="07"]')).to_contain_text("Чат закрыт без итога и прощания.")


def test_coaching_moments_from_state_only(page: Page, web_url: str) -> None:
    requests = open_page(page, web_url, "#/coaching")
    switch = page.locator('[data-act="coach"]')
    expect(switch).to_have_count(6)
    expect(switch.first).to_have_text("04 Корректная и полная консультация: 4")
    expect(switch.first).to_have_attribute("aria-pressed", "true")
    moments = page.locator('[aria-label="Где теряем баллы"] article')
    expect(moments).to_have_count(4)
    expect(moments.first).to_contain_text("Как сказать лучше")
    expect(page.locator('[aria-label="Где теряем баллы"]')).to_contain_text("Я передам вопрос специалистам.")
    expect(moments.locator('a[href="#/d/call-024"]')).to_have_count(1)
    expect(page.locator('[aria-label="Как звучит хороший ответ"]')).to_contain_text("Примеры появятся")
    page.click('[data-act="coach"][data-cid="07"]')
    expect(moments).to_have_count(2)
    assert requests == ["GET /state"]


def test_meeting_sheet_collects_and_copies(page: Page, context: BrowserContext, web_url: str) -> None:
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    open_page(page, web_url, "#/coaching")
    copy = page.locator('[data-act="copy"]')
    expect(copy).to_be_disabled()
    picks = page.locator('[data-act="pick"]')
    picks.nth(0).check()
    picks.nth(1).check()
    expect(page.locator('[data-act="sheet"]')).to_have_text("Разбор для встречи: 2")
    expect(page.locator("#sheet li")).to_have_count(2)
    expect(page.locator('[data-act="print"]')).to_be_enabled()
    copy.click()
    expect(page.locator("#toast")).to_contain_text("скопирован")
    clip = page.evaluate("navigator.clipboard.readText()")
    assert clip == page.locator("#sheet ol").inner_text()
    assert "Лучше:" in clip
