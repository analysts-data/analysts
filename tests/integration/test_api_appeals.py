"""POST /api/appeals, /api/appeals/{id}/decision, /api/decisions (review-workflow, задача 5.7)."""

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprint

APPEAL = {
    "dlg": "p1-ru-003",
    "cid": "04",
    "ask": 10,
    "ev": [8],
    "comment": "Срок вывода назван, это существенная часть ответа.",
    "by": "Оператор",
}
DECISION = {"to": 10, "reason": "Срок вывода назван полностью", "reviewer": "Проверяющий"}
REVIEW = {
    "dlg": "call-024",
    "cid": "04",
    "from": 15,
    "to": 10,
    "reason": "Срок ответа клиенту не назван",
    "reviewer": "Специалист КК",
}
FLAG = {"insult": False, "paid": True, "leak": False}
CLEAR = {"insult": False, "paid": False, "leak": False}


@pytest.fixture(autouse=True)
def results(store: Store) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    c04 = next(c for c in checklist.criteria if c.id == "04")
    store.add_result("p1-ru-003", "04", 3, fingerprint(checklist, c04, "chat"), CriterionResult(a=5))
    store.add_result("call-024", "04", 3, fingerprint(checklist, c04, "call"), CriterionResult(a=15, alt=10))
    c08 = next(c for c in checklist.criteria if c.id == "08")
    store.add_result("p1-ru-003", "08", 3, fingerprint(checklist, c08, "chat"), CriterionResult(a=FLAG))


def state_of(client: TestClient, dlg: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = client.get("/api/state").json()
    return next(d for d in state["dialogs"] if d["id"] == dlg), state["appeals"]


def test_appeal_is_filed_from_current_answer(client: TestClient) -> None:
    response = client.post("/api/appeals", json=APPEAL)

    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("id", "kind", "from", "ask", "to", "status")} == {
        "id": "a1",
        "kind": "appeal",
        "from": 5,
        "ask": 10,
        "to": None,
        "status": "pending",
    }
    assert re.fullmatch(r"\d{2}\.\d{2} \d{2}:\d{2}", body["at"])


def test_decision_sits_next_to_unchanged_model_answer(client: TestClient) -> None:
    client.post("/api/appeals", json=APPEAL)

    response = client.post("/api/appeals/a1/decision", json=DECISION)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["to"], body["reviewer"]) == ("changed", 10, "Проверяющий")
    assert body["decidedAt"]
    dialog, appeals = state_of(client, "p1-ru-003")
    assert dialog["res"]["04"]["a"] == 5
    assert [(a["id"], a["to"], a["status"]) for a in appeals] == [("a1", 10, "changed")]


def test_flag_appeal_and_decision_carry_objects_and_keep_model_answer(client: TestClient) -> None:
    filed = client.post("/api/appeals", json=APPEAL | {"cid": "08", "ask": CLEAR})
    assert filed.status_code == 200
    assert (filed.json()["from"], filed.json()["ask"]) == (FLAG, CLEAR)

    decided = client.post("/api/appeals/a1/decision", json=DECISION | {"to": CLEAR})

    assert (decided.status_code, decided.json()["status"], decided.json()["to"]) == (200, "changed", CLEAR)
    dialog, appeals = state_of(client, "p1-ru-003")
    assert dialog["res"]["08"]["a"] == FLAG
    assert [(a["cid"], a["to"]) for a in appeals] == [("08", CLEAR)]


@pytest.mark.parametrize("ask", [CLEAR | {"paid": 0}, CLEAR | {"paid": "false"}, CLEAR | {"paid": None}])
def test_flag_appeal_values_must_be_booleans(client: TestClient, ask: dict[str, object]) -> None:
    response = client.post("/api/appeals", json=APPEAL | {"cid": "08", "ask": ask})

    assert response.status_code == 422
    assert client.get("/api/state").json()["appeals"] == []


def test_review_accepts_second_opinion_without_ask(client: TestClient) -> None:
    response = client.post("/api/decisions", json=REVIEW)

    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("kind", "from", "to", "status", "by")} == {
        "kind": "review",
        "from": 15,
        "to": 10,
        "status": "changed",
        "by": "Специалист КК",
    }
    assert "ask" not in body
    dialog, appeals = state_of(client, "call-024")
    assert dialog["res"]["04"]["a"] == 15
    assert "ask" not in appeals[0]


@pytest.mark.parametrize(
    ("path", "body", "status", "detail"),
    [
        ("/api/appeals", APPEAL | {"dlg": "nope"}, 404, "Диалог nope не найден"),
        (
            "/api/appeals",
            APPEAL | {"ask": 12},
            422,
            "Ответ 12 недопустим для критерия 04: допустимы 20, 15, 10, 5, 0, na",
        ),
        (
            "/api/appeals",
            APPEAL | {"cid": "08", "ask": {"insult": True}},
            422,
            "Ответ по флагу 08 — объект с ключами insult, paid, leak и значениями true или false",
        ),
        ("/api/appeals/a999/decision", DECISION, 404, "Апелляция a999 не найдена"),
        (
            "/api/decisions",
            REVIEW | {"from": 10},
            409,
            "Текущий ответ по критерию 04: 15. Обновите страницу.",
        ),
        (
            "/api/decisions",
            REVIEW | {"dlg": "p1-ru-003", "from": 5},
            422,
            "По критерию 04 модели не расходятся и основание прошло проверку",
        ),
    ],
)
def test_refusals_carry_status_and_detail(
    client: TestClient, path: str, body: dict[str, Any], status: int, detail: str
) -> None:
    response = client.post(path, json=body)

    assert (response.status_code, response.json()) == (status, {"detail": detail})


def test_decision_conflicts_and_empty_reason(client: TestClient) -> None:
    client.post("/api/appeals", json=APPEAL)
    again = client.post("/api/appeals", json=APPEAL)
    assert (again.status_code, again.json()) == (
        409,
        {"detail": "По критерию 04 уже есть a1 на рассмотрении"},
    )

    empty = client.post("/api/appeals/a1/decision", json=DECISION | {"reason": ""})
    assert empty.status_code == 422
    assert empty.json() == {"detail": "Причина решения обязательна: не короче 5 символов"}
    assert state_of(client, "p1-ru-003")[1][0]["status"] == "pending"

    client.post("/api/appeals/a1/decision", json=DECISION)
    twice = client.post("/api/appeals/a1/decision", json=DECISION)
    assert (twice.status_code, twice.json()) == (409, {"detail": "Апелляция a1 уже рассмотрена: changed"})


def test_body_without_reason_is_rejected_by_schema(client: TestClient) -> None:
    assert (
        client.post("/api/decisions", json={k: v for k, v in REVIEW.items() if k != "reason"}).status_code
        == 422
    )
