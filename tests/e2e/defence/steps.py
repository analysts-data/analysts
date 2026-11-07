"""Шаги сценария защиты на публичном API и интерфейсе (design, решения 10 и 11).

Локаторы — таблица «Интерфейс» `design/ports.md`. Ожидаемые ответы не зашиты: шаги читают
`GET /api/state` (то, что записано в кассетах) и сверяют экран с ним и с `web/js/scoring.js`.
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUN_TIMEOUT_S = 60

GROSS = ("p1-ru-022", "p1-ru-009", "p1-kz-015", "p1-ru-029")  # грубые ошибки набора
CARD = "p1-ru-022"


@dataclass
class Defence:
    page: Page
    api: httpx.Client
    console_errors: list[str] = field(default_factory=list)

    def go(self, route: str) -> None:
        self.page.goto(f"{self.api.base_url}{route}")

    def state(self) -> dict[str, Any]:
        return self.api.get("/api/state").raise_for_status().json()

    @property
    def body(self) -> Locator:
        return self.page.locator("body")


def queue(d: Defence) -> None:
    """Список (60 с): грубые ошибки наверху, причина в аналитике ведёт к диалогу, строка — к карточке."""
    s = d.state()
    ids = [x["id"] for x in s["dialogs"]]
    gross = {x["id"] for x in s["dialogs"] if flags_of(x, s["checklist"])}
    assert set(GROSS) <= gross, f"грубые ошибки в ответах модели: {sorted(gross)}"
    d.go("#/queue")
    rows = d.page.locator('[data-act="open"][data-id]')
    expect(rows).to_have_count(len(ids))
    order = rows.evaluate_all("rows => rows.map(r => r.dataset.id)")
    first_clean = min(i for i, x in enumerate(order) if x not in gross)
    assert all(order.index(x) < first_clean for x in gross), order

    d.go("#/analytics")
    reason = d.page.locator('[data-view="analytics"] a[href^="#/d/"]').first
    href = reason.get_attribute("href") or ""
    assert href.removeprefix("#/d/") in ids, href
    reason.click()
    expect(d.page).to_have_url(re.compile(re.escape(href) + "$"))

    d.go("#/queue")
    d.page.locator(f'[data-act="open"][data-id="{CARD}"]').click()
    expect(d.page).to_have_url(re.compile(f"#/d/{CARD}$"))


def wait_run(api: httpx.Client, run_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while (run := api.get(f"/api/runs/{run_id}").raise_for_status().json())["status"] == "running":
        assert time.monotonic() < deadline, f"запуск {run_id} идёт дольше {RUN_TIMEOUT_S} с: {run}"
        time.sleep(0.2)
    return run


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def flags_of(dlg: dict[str, Any], checklist: dict[str, Any]) -> list[str]:
    """Подписи найденных нарушений, как `flagsOf` в `web/js/scoring.js`."""
    flags = [c for c in checklist["criteria"] if c["type"] == "flag" and c["id"] in dlg["res"]]
    return [q["label"] for c in flags for q in c["questions"] if dlg["res"][c["id"]]["a"].get(q["k"])]
