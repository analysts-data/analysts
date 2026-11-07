"""Решение проверяющего следует за смыслом критерия (review-workflow, задача 5.8; design, решение 12)."""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprint
from fakes import FakeEvaluator


@pytest.fixture
def evaluator() -> FakeEvaluator:
    """Новая оценка `04` у p1-ru-003 после замены критерия — 15."""
    return FakeEvaluator(res={"p1-ru-003": {"04": CriterionResult(a=15)}})


@pytest.fixture(autouse=True)
def decided(client: TestClient, store: Store) -> dict[str, Any]:
    """Исходный ответ модели 5, апелляция и решение `changed` с `to: 10`."""
    checklist = store.current_checklist()
    assert checklist is not None
    c04 = next(c for c in checklist.criteria if c.id == "04")
    store.add_result("p1-ru-003", "04", 3, fingerprint(checklist, c04), CriterionResult(a=5))
    client.post(
        "/api/appeals",
        json={
            "dlg": "p1-ru-003",
            "cid": "04",
            "ask": 10,
            "comment": "Срок вывода назван, это важно.",
            "by": "Оператор",
        },
    )
    decision = client.post(
        "/api/appeals/a1/decision",
        json={"to": 10, "reason": "Срок назван полностью", "reviewer": "Проверяющий"},
    )
    assert decision.json()["status"] == "changed"
    return client.get("/api/state").json()["checklist"]


def edit_04(checklist: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return checklist | {"criteria": [c | fields if c["id"] == "04" else c for c in checklist["criteria"]]}


def p1_ru_003(client: TestClient) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = client.get("/api/state").json()
    return next(d for d in state["dialogs"] if d["id"] == "p1-ru-003"), state["appeals"]


def run_to_end(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    run_id = client.post("/api/runs", json=body).json()["run_id"]
    deadline = time.monotonic() + 2
    while True:
        progress = client.get(f"/api/runs/{run_id}").json()
        if progress["done"] == progress["total"] or time.monotonic() > deadline:
            return progress
        time.sleep(0.02)


def test_new_meaning_drops_old_decision(client: TestClient, decided: dict[str, Any]) -> None:
    saved = client.put("/api/checklist", json=edit_04(decided, text="Новый смысл критерия 04."))
    assert saved.json() == {"version": 4, "pending": ["04"]}

    progress = run_to_end(client, {"criteria": ["04"]})

    assert progress["done"] == progress["total"] == 2
    dialog, appeals = p1_ru_003(client)
    assert dialog["res"]["04"]["a"] == 15
    assert appeals == []


def test_weight_change_keeps_decision(client: TestClient, decided: dict[str, Any]) -> None:
    saved = client.put("/api/checklist", json=edit_04(decided, w=25))
    assert saved.json() == {"version": 4, "pending": []}

    dialog, appeals = p1_ru_003(client)
    assert dialog["res"]["04"]["a"] == 5
    assert [(a["id"], a["to"], a["status"]) for a in appeals] == [("a1", 10, "changed")]
