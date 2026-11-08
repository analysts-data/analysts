"""Сценарии `specs/cqa-shell` изменения react-frontend: сборка, /legacy/, текст из данных, палитра, тема."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
STATE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"
STATE = STATE_PATH.read_text(encoding="utf-8")
DIALOGS = len(json.loads(STATE)["dialogs"])
XSS = "<img src=x onerror=alert(1)>"


def serve(page: Page, body: str = STATE) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    return errors


def test_every_request_stays_on_the_page_origin(page: Page, web_url: str) -> None:
    serve(page)
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    page.goto(f"{web_url}/#/queue")
    expect(page.locator("#bQueue")).to_have_text("7")  # state loaded
    page.wait_for_load_state("networkidle")
    assert urls and all(u.startswith(web_url) for u in urls), [u for u in urls if not u.startswith(web_url)]


def test_legacy_interface_opens_with_the_same_api(page: Page, web_url: str) -> None:
    errors = serve(page)
    page.goto(f"{web_url}/legacy/#/queue")
    expect(page.locator('[data-view="queue"] [data-act="open"][data-id]')).to_have_count(DIALOGS)
    assert errors == []


def test_markup_from_data_is_shown_as_text(page: Page, web_url: str) -> None:
    state = json.loads(STATE)
    state["checklist"]["criteria"][0]["name"] = XSS
    dlg = next(d for d in state["dialogs"] if d["id"] == "p1-ru-003")
    dlg["lines"][0]["text"] = XSS
    serve(page, json.dumps(state))
    page.goto(f"{web_url}/#/d/p1-ru-003")
    view = page.locator('[data-view="d"]')
    expect(view).to_contain_text(XSS)
    expect(view.locator("img")).to_have_count(0)


def test_palette_opens_a_dialog_by_id(page: Page, web_url: str) -> None:
    errors = serve(page)
    page.goto(f"{web_url}/#/queue")
    expect(page.locator("#bQueue")).to_have_text("7")  # state loaded
    page.keyboard.press("Control+k")
    page.get_by_role("dialog").get_by_role("combobox").fill("p1-ru-003")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"#/d/p1-ru-003$"))
    expect(page.locator('[data-view="d"]')).to_be_visible()
    assert errors == []


def test_dark_theme_survives_reload(page: Page, web_url: str) -> None:
    serve(page)
    page.emulate_media(color_scheme="light")
    page.goto(f"{web_url}/#/queue")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.locator('[data-act="theme"]').click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_theme_defaults_to_the_system_setting(page: Page, web_url: str) -> None:
    serve(page)
    page.emulate_media(color_scheme="dark")
    page.goto(f"{web_url}/#/queue")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
