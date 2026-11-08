"""Экран «Пакеты»: список с прогрессом, «Новый пакет» по фильтрам, страница пакета с батчами и пауза.

Ответы /api/batches — по design/contract.md, «Пакетная обработка» (ветка eval-and-delivery-batches).
"""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e

STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)
RATE = {"rpm": 60, "parallel": 4}
JOB = {
    "id": 1,
    "status": "running",
    "priority": "normal",
    "batch_size": 5,
    "force": False,
    "note": None,
    "created": "2026-11-08T03:00:00Z",
    "total": 10,
    "done": 6,
    "errors": 1,
    "pending": 4,
    "cost": 0.12,
    "throughput_per_min": 2.5,
    "eta_s": 96,
    "eta_basis": "по скорости последних 3 батчей",
}
NEW = {
    **JOB,
    "id": 2,
    "status": "queued",
    "priority": "high",
    "total": 4,
    "done": 2,
    "errors": 0,
    "batches": [
        {
            "no": 1,
            "n": 2,
            "done": 2,
            "errors": 0,
            "started": "2026-11-08T04:00:00Z",
            "finished": "2026-11-08T04:01:00Z",
            "cost": 0.02,
            "run_id": 7,
        },
        {
            "no": 2,
            "n": 2,
            "done": 0,
            "errors": 0,
            "started": None,
            "finished": None,
            "cost": 0,
            "run_id": None,
        },
    ],
    "failed": [],
}


def test_new_batch_from_filters_then_pause_it(page: Page, web_url: str) -> None:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    posts: list[tuple[str, Any]] = []
    new = copy.deepcopy(NEW)

    def batches(route: Route) -> None:
        req = route.request
        path = re.sub(r"^.*/api", "", req.url)
        if req.method == "POST":
            posts.append((path, req.post_data_json if req.post_data else None))
            if path == "/batches/2/pause":
                new["status"] = "paused"
            return route.fulfill(json={**new, "rate_limit": RATE})
        if path == "/batches":
            return route.fulfill(json={"jobs": [JOB], "rate_limit": RATE})
        route.fulfill(json={**new, "rate_limit": RATE})

    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route("**/api/batches**", batches)
    page.goto(f"{web_url}/#/batches")

    row = page.locator('[data-job="1"]')
    expect(row).to_contain_text("Идёт")
    expect(row).to_contain_text("6 из 10 диалогов")
    expect(row).to_contain_text("2 мин")
    expect(page.get_by_text("Лимит модели: 60 запросов в минуту, до 4 одновременно.")).to_be_visible()

    page.get_by_role("button", name="Новый пакет").first.click()
    dlg = page.get_by_role("dialog", name="Новый пакет")
    dlg.get_by_label("Канал").select_option("call")
    dlg.get_by_label("Приоритет").select_option("high")
    dlg.get_by_label("Размер батча").fill("2")
    dlg.get_by_role("button", name="Создать пакет").click()

    expect(page).to_have_url(re.compile(r"#/batches/2$"))
    assert posts[0] == (
        "/batches",
        {"filter": {"ch": "call", "unscored_only": True}, "batch_size": 2, "priority": "high"},
    )
    expect(page.locator("[data-view] h1")).to_contain_text("Пакет 2")
    expect(page.locator("[data-batch]")).to_have_count(2)
    expect(page.locator('[data-act="batch-resume"]')).to_be_disabled()
    expect(page.get_by_text("Только для пакета на паузе.")).to_be_visible()

    page.locator('[data-act="eta-why"]').click()
    expect(page.get_by_text("Оценка времени: по скорости последних 3 батчей.")).to_be_visible()

    page.locator('[data-act="batch-pause"]').click()
    expect(page.locator("[data-view] h1")).to_contain_text("На паузе")
    assert posts[-1] == ("/batches/2/pause", None)
    expect(page.locator('[data-act="batch-resume"]')).to_be_enabled()
    expect(page.locator('[data-act="batch-pause"]')).to_be_disabled()
    assert errors == []
