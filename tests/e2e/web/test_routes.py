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


@pytest.mark.parametrize(
    ("route", "view"),
    [
        ("queue", "queue"),
        ("d/call-024", "d"),
        ("appeals", "appeals"),
        ("appeals/a1", "appeals"),
        ("checklist", "checklist"),
        ("analytics", "analytics"),
        ("coaching", "coaching"),
    ],
)
def test_every_route_renders_on_phone_width_without_errors(
    page: Page, web_url: str, route: str, view: str
) -> None:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("requestfailed", lambda r: problems.append(f"failed {r.url}"))
    page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{web_url}/#/{route}")
    expect(page.locator(f'[data-view="{view}"] h1').first).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
