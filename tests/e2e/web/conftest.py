import json
import threading
from collections.abc import Callable, Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

WEB = Path(__file__).resolve().parents[3] / "web"
STATE = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="session")
def web_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(WEB)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def live_config(page: Page) -> None:
    """GET /api/config для плашки режима: у статического сервера нет API, а 404 — ошибка в консоли."""
    page.route(
        "**/api/config",
        lambda r: r.fulfill(status=200, content_type="application/json", body='{"llm_mode": "live"}'),
    )


@pytest.fixture(autouse=True)
def quiet_prosody(page: Page) -> None:
    """GET /api/dialogs/{id}/prosody для карточки звонка: пустой разбор вместо 404 статического сервера."""
    page.route(
        "**/api/dialogs/*/prosody",
        lambda r: r.fulfill(status=200, content_type="application/json", body=EMPTY_PROSODY),
    )


EMPTY_PROSODY = '{"lines": [], "speakers": {"client": null, "operator": null}, "summary": []}'


@pytest.fixture
def open_card(page: Page, web_url: str) -> Callable[..., list[str]]:
    """Open `#/d/{id}` on the prototype state; `edit(dialog)` may change that dialog first.

    Returns the list of console errors, filled while the test runs.
    """

    def go(dialog_id: str, edit: Callable[[dict[str, Any]], None] | None = None) -> list[str]:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if edit:
            edit(next(d for d in state["dialogs"] if d["id"] == dialog_id))
        body = json.dumps(state)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(
            "**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=body)
        )
        page.goto(f"{web_url}/#/d/{dialog_id}")
        expect(page.locator('[data-view="d"] h1')).to_be_visible()  # state loaded and card drawn
        return errors

    return go
