import io
import re
import wave
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect
from test_card import dialog, open_card  # noqa: F401  (open_card is a fixture)

pytestmark = pytest.mark.e2e


def silence_wav(seconds: int = 60, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(b"\x80" * rate * seconds)
    return buf.getvalue()


def line(state: dict[str, Any], n: int) -> dict[str, Any]:
    return next(ln for ln in dialog(state, "call-024")["lines"] if ln.get("n") == n)


def test_seek_from_evidence_plays_from_line_start(page: Page, open_card: Callable[..., list[str]]) -> None:
    def start_line_2_at_4_1(state: dict[str, Any]) -> None:
        line(state, 2)["s"] = line(state, 2)["t"] = 4.1

    wav = silence_wav()
    page.route("**/api/dialogs/*/audio", lambda r: r.fulfill(status=200, content_type="audio/wav", body=wav))
    errors = open_card("call-024", start_line_2_at_4_1)
    expect(page.locator("audio")).to_have_attribute("preload", "none")
    page.click('.crit[data-cid="01"] [data-act="crit"]')
    page.click('.crit-body [data-act="seek"][data-n="2"]')
    page.wait_for_function(
        "() => { const a = document.querySelector('audio');"
        " return a && !a.paused && Math.abs(a.currentTime - 4.1) <= 0.5; }"
    )
    expect(page.locator('#tr [data-n="2"]')).to_have_class(re.compile(r"\bnow\b"))
    assert errors == []


def test_wave_colours_roles_and_hatches_the_hold(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("call-024")
    for cls in ("wc", "wo", "wi"):
        assert page.locator(f".wave .bars .{cls}").count() > 0, cls
    assert page.locator(".wave .hatch").count() >= 1
    expect(page.locator(".wave")).to_contain_text("не оценивается")
    assert errors == []


def test_chat_has_no_player(page: Page, open_card: Callable[..., list[str]]) -> None:
    errors = open_card("p1-ru-003")
    expect(page.locator(".player")).to_have_count(0)
    expect(page.locator("audio")).to_have_count(0)
    expect(page.locator('[data-act="seek"]')).to_have_count(0)
    assert errors == []


def test_line_without_start_links_to_org_player(page: Page, open_card: Callable[..., list[str]]) -> None:
    def drop_start_of_line_3(state: dict[str, Any]) -> None:
        del line(state, 3)["s"]

    errors = open_card("call-024", drop_start_of_line_3)
    row = page.locator('#tr [data-n="3"]')
    expect(row.locator('[data-act="seek"]')).to_have_count(0)
    link = row.get_by_role("link", name="Открыть в плеере")
    expect(link).to_have_attribute("href", "/api/dialogs/call-024/player")
    expect(link).to_have_attribute("target", "_blank")
    assert errors == []
