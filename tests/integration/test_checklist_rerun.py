"""A weight or name change re-evaluates nothing; a meaning change re-evaluates only that criterion."""

import sqlite3
import time
from typing import Any

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource


def _run(client: TestClient, criteria: list[str] | None = None) -> dict[str, Any]:
    run_id = client.post("/api/runs", json={"dialogs": None, "criteria": criteria}).json()["run_id"]
    deadline = time.monotonic() + 2
    while (progress := client.get(f"/api/runs/{run_id}").json())["status"] == "running":
        assert time.monotonic() < deadline, "run did not finish within 2 seconds"
        time.sleep(0.01)
    return progress


def _edit(client: TestClient, changes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    draft = client.get("/api/state").json()["checklist"]
    for c in draft["criteria"]:
        c.update(changes.get(c["id"], {}))
    return draft


def _res(client: TestClient) -> dict[str, dict[str, Any]]:
    return {d["id"]: d["res"] for d in client.get("/api/state").json()["dialogs"]}


def test_only_a_meaning_change_calls_the_model_again(
    settings: Settings, store: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> None:
    with TestClient(create_app(settings, source=FakeSource(), evaluator=evaluator, conn=conn)) as client:
        assert _run(client)["done"] == 16
        calls = evaluator.calls

        draft = _edit(client, {"06": {"w": 10}, "01": {"name": "Приветствие и представление"}})
        assert client.put("/api/checklist", json=draft).json() == {"version": 4, "pending": []}
        progress = _run(client)
        assert (progress["total"], progress["status"]) == (0, "done")
        assert evaluator.calls == calls

        draft = _edit(client, {"04": {"text": "Оцените ответ по шкале, учитывая срок решения."}})
        assert client.put("/api/checklist", json=draft).json() == {"version": 5, "pending": ["04"]}
        assert all("04" not in res for res in _res(client).values())

        seen = len(evaluator.seen)
        assert _run(client, ["04"])["total"] == 2
        assert set(evaluator.seen[seen:]) == {"04"}
        assert all("04" in res for res in _res(client).values())
