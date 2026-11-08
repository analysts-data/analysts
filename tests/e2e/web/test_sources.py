import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)
SRC = {
    "id": "src1",
    "name": "Zendesk RU",
    "kind": "http_json",
    "service": "Zendesk",
    "channel_default": "chat",
    "product_default": None,
    "config": {
        "url": "https://zd.test/export",
        "method": "GET",
        "records_path": "items",
        "auth_header": "",
        "mapping": {"conversation_id": "id", "transcript": "messages", "speaker": "role", "text": "text"},
    },
    "has_secret": False,
    "enabled": True,
    "schedule_min": 60,
    "archived": False,
}
SYNC = {
    "id": 3,
    "source_id": "src1",
    "started": "2026-11-08T06:40:00+05:00",
    "finished": "2026-11-08T06:40:02+05:00",
    "status": "partial",
    "added": 12,
    "skipped": 2,
    "errors": ["c7: нет transcript"],
    "duration_ms": 2100,
}
STATS: list[dict[str, Any]] = [
    {
        "id": "src1",
        "dialogs": 40,
        "scored": 31,
        "avg_total": 82.5,
        "gross_share": 0.1,
        "running": None,
        "last_sync": SYNC,
        "error_rate": 0.0,
        "freshness_s": 1800,
        "health": "warning",
        "basis": "последняя синхронизация с пропусками: 1 запись не разобраны",
    }
]
PREVIEW = {
    "ok": True,
    "error": None,
    "ms": 40,
    "records": 1,
    "errors": [],
    "paths": ["ticket", "msgs"],
    "preview": [
        {
            "id": "new-t1",
            "external_id": "t1",
            "title": "t1",
            "ch": "chat",
            "lang": "ru",
            "lines": 2,
            "operator": None,
            "product": None,
            "sample": [{"who": "client", "text": "Здравствуйте"}],
        }
    ],
}


def test_sources_health_sync_and_webhook_wizard(page: Page, web_url: str) -> None:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    sent: dict[str, Any] = {}

    def api(route: Route) -> None:
        req, path = route.request, re.sub(r"^.*/api", "", route.request.url.split("?")[0])
        out: Any = None
        data: Any = req.post_data_json
        if path == "/sources" and req.method == "POST":
            sent["create"] = data
            out = {
                **data,
                "id": "src2",
                "has_secret": True,
                "ingest_path": "/api/sources/src2/ingest",
                "token": "tok-once-123",
            }
        elif path == "/sources":
            out = [SRC]
        elif path == "/sources/stats":
            out = STATS
        elif path == "/sources/test":
            sent["test"] = data
            out = PREVIEW
        elif path == "/sources/src1/sync":
            out = {**SYNC, "status": "ok", "added": 5, "skipped": 1, "errors": []}
        elif path == "/sources/src1/syncs":
            out = [SYNC]
        route.fulfill(
            status=200 if out is not None else 404, content_type="application/json", body=json.dumps(out)
        )

    page.route(re.compile(r".*/api/sources.*"), api)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{web_url}/#/sources")

    card = page.locator('[data-source="src1"]')
    expect(card.locator("h2")).to_have_text("Zendesk RU")
    expect(card.locator("[data-health]")).to_have_text("Внимание")
    expect(card).to_contain_text("40 / 31")
    expect(card).to_contain_text("30 мин назад")
    card.locator("[data-act=health-why]").click()
    expect(card.locator("[data-basis]")).to_have_text(STATS[0]["basis"])

    card.locator("[data-act=source-sync]").click()
    expect(page.locator("#toast")).to_contain_text("Синхронизация «Zendesk RU»: добавлено 5, пропущено 1.")
    card.locator("[data-act=source-log]").click()
    expect(page.get_by_role("dialog").locator("tbody tr")).to_have_count(1)
    expect(page.get_by_role("dialog")).to_contain_text("c7: нет transcript")
    page.keyboard.press("Escape")

    page.locator("[data-act=source-add]").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("radio", name=re.compile("^Webhook")).check()
    dialog.locator("[data-act=source-next]").click()
    dialog.get_by_label("Название").fill("Чат-бот KZ")
    dialog.locator("[data-act=source-next]").click()
    dialog.get_by_label("Пример тела запроса (JSON)").fill(
        '{"id": "t1", "messages": [{"role": "client", "text": "Здравствуйте"}]}'
    )
    expect(dialog.locator('[aria-label="Предпросмотр"] tbody tr')).to_have_text(
        re.compile("t1.*client: Здравствуйте")
    )
    assert sent["test"]["kind"] == "webhook" and sent["test"]["sample"]["id"] == "t1"
    dialog.locator("[data-act=source-next]").click()
    expect(dialog.locator("[data-test-result=ok]")).to_contain_text("Записей в ответе: 1")
    dialog.locator("[data-act=source-save]").click()

    expect(dialog.locator("[data-step=token]")).to_contain_text("Токен показан один раз")
    expect(dialog.get_by_label("Токен")).to_have_value("tok-once-123")
    expect(dialog.get_by_label("Адрес webhook")).to_have_value(re.compile(r"/api/sources/src2/ingest$"))
    dialog.locator("[data-act=copy-token]").click()
    expect(page.locator("#toast")).to_contain_text("Скопировано.")
    assert sent["create"]["name"] == "Чат-бот KZ" and sent["create"]["config"]["mapping"]["text"] == "text"
    dialog.locator("[data-act=source-done]").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert problems == []
