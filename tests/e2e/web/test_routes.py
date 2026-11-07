from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)


def test_analytics_and_coaching_stubs_switch_by_hash_without_reload(page: Page, web_url: str) -> None:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route(
        "**/api/state", lambda route: route.fulfill(status=200, content_type="application/json", body=STATE)
    )
    page.goto(f"{web_url}/#/analytics")
    expect(page.locator('[data-view="analytics"] h1')).to_have_text("Аналитика")
    page.evaluate("window.__sameDocument = true")
    page.evaluate("location.hash = '#/coaching'")
    expect(page.locator('[data-view="coaching"] h1')).to_have_text("Обучение")
    assert page.evaluate("window.__sameDocument") is True
    assert page.evaluate("document.activeElement.id") == "view"
    assert errors == []
