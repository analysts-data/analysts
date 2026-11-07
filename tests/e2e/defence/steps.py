"""Шаги сценария защиты на публичном API и интерфейсе (design, решения 10 и 11).

Локаторы — таблица «Интерфейс» `design/ports.md`. Ожидаемые ответы не зашиты: шаги читают
`GET /api/state` (то, что записано в кассетах) и сверяют экран с ним и с `web/js/scoring.js`.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUN_TIMEOUT_S = 60


@dataclass
class Defence:
    page: Page
    api: httpx.Client
    console_errors: list[str] = field(default_factory=list)

    def go(self, route: str) -> None:
        self.page.goto(f"{self.api.base_url}{route}")

    def state(self) -> dict[str, Any]:
        return self.api.get("/api/state").raise_for_status().json()


def wait_run(api: httpx.Client, run_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while (run := api.get(f"/api/runs/{run_id}").raise_for_status().json())["status"] == "running":
        assert time.monotonic() < deadline, f"запуск {run_id} идёт дольше {RUN_TIMEOUT_S} с: {run}"
        time.sleep(0.2)
    return run


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())
