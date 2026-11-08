"""GET/PUT /api/appeals/reasons, reason_code в решениях, GET /api/appeals/stats (reason-codes)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult, Dialog
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
    "to": 15,
    "reason": "Срок ответа клиенту назван",
    "reviewer": "Специалист КК",
}
CLEAR = {"insult": False, "paid": False, "leak": False}


@pytest.fixture(autouse=True)
def results(store: Store, dialogs: list[Dialog]) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    store.add_dialogs([dialogs[0].model_copy(update={"id": "kz-1", "lang": "KZ"})], {})
    by_id = {c.id: c for c in checklist.criteria}

    def add(dlg: str, ch: str, cid: str, result: CriterionResult) -> None:
        store.add_result(dlg, cid, 3, fingerprint(checklist, by_id[cid], ch), result)

    add("p1-ru-003", "chat", "04", CriterionResult(a=5))
    add("p1-ru-003", "chat", "01", CriterionResult(a="yes"))
    add("p1-ru-003", "chat", "08", CriterionResult(a=CLEAR))
    add("call-024", "call", "04", CriterionResult(a=15, alt=10))


def test_catalogue_is_seeded_and_editable(client: TestClient) -> None:
    seeded = client.get("/api/appeals/reasons")
    assert seeded.status_code == 200
    assert len(seeded.json()) == 7
    assert seeded.json()[0] == {
        "code": "misread",
        "label": "Модель неверно поняла реплику",
        "applies": "changed",
    }

    mine = [{"code": "script", "label": "Нарушен скрипт", "applies": "both"}]
    saved = client.put("/api/appeals/reasons", json=mine)

    assert (saved.status_code, saved.json()) == (200, mine)
    assert client.get("/api/appeals/reasons").json() == mine


def test_catalogue_save_and_coded_decision_land_in_the_audit(client: TestClient) -> None:
    client.put(
        "/api/appeals/reasons", json=[{"code": "script", "label": "Нарушен скрипт", "applies": "both"}]
    )
    client.post("/api/appeals", json=APPEAL)
    client.post("/api/appeals/a1/decision", json=DECISION | {"reason_code": "script"})

    entries = client.get("/api/audit").json()

    assert [(e["action"], e["details"]) for e in entries] == [
        ("appeal.decide", {"status": "changed", "reason_code": "script"}),
        ("appeal.file", {"dlg": "p1-ru-003", "cid": "04"}),
        ("reasons.save", {"codes": ["script"]}),
    ]


def test_catalogue_refusals_are_russian(client: TestClient) -> None:
    twice = [{"code": "x", "label": "а", "applies": "both"}] * 2

    response = client.put("/api/appeals/reasons", json=twice)

    assert (response.status_code, response.json()) == (422, {"detail": "Код причины x повторяется"})
    assert (
        client.put("/api/appeals/reasons", json=[{"code": "x", "label": "а", "applies": "nope"}]).status_code
        == 422
    )


def test_decision_and_review_carry_reason_code_into_state(client: TestClient) -> None:
    client.post("/api/appeals", json=APPEAL)

    decided = client.post("/api/appeals/a1/decision", json=DECISION | {"reason_code": "misread"})
    reviewed = client.post("/api/decisions", json=REVIEW | {"reason_code": "by_rules"})

    assert (decided.status_code, decided.json()["reason_code"]) == (200, "misread")
    assert (reviewed.status_code, reviewed.json()["reason_code"]) == (200, "by_rules")
    appeals = client.get("/api/state").json()["appeals"]
    assert [(a["id"], a["reason_code"]) for a in appeals] == [("a1", "misread"), ("a2", "by_rules")]


def test_decision_without_reason_code_returns_null(client: TestClient) -> None:
    client.post("/api/appeals", json=APPEAL)

    decided = client.post("/api/appeals/a1/decision", json=DECISION)

    assert (decided.status_code, decided.json()["reason_code"]) == (200, None)


@pytest.mark.parametrize(
    ("path", "body", "detail"),
    [
        (
            "/api/appeals/a1/decision",
            DECISION | {"reason_code": "nope"},
            "Неизвестный код причины nope: допустимы misread, context, ambiguous, asr, violation, "
            "by_rules, other",
        ),
        (
            "/api/appeals/a1/decision",
            DECISION | {"reason_code": "violation"},
            "Причина «Нарушение подтверждено» не подходит к решению «оценка изменена»",
        ),
        (
            "/api/decisions",
            REVIEW | {"reason_code": "misread"},
            "Причина «Модель неверно поняла реплику» не подходит к решению «оценка оставлена»",
        ),
    ],
)
def test_wrong_reason_code_is_refused_and_nothing_is_decided(
    client: TestClient, path: str, body: dict[str, Any], detail: str
) -> None:
    client.post("/api/appeals", json=APPEAL)

    response = client.post(path, json=body)

    assert (response.status_code, response.json()) == (422, {"detail": detail})
    appeals = client.get("/api/state").json()["appeals"]
    assert [(a["id"], a["status"]) for a in appeals] == [("a1", "pending")]


def test_removed_code_is_no_longer_accepted(client: TestClient) -> None:
    client.put(
        "/api/appeals/reasons", json=[{"code": "script", "label": "Нарушен скрипт", "applies": "both"}]
    )
    client.post("/api/appeals", json=APPEAL)

    response = client.post("/api/appeals/a1/decision", json=DECISION | {"reason_code": "misread"})

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "Неизвестный код причины misread: допустимы script"},
    )


def test_stats_show_reasons_and_share_modified_by_people(client: TestClient) -> None:
    client.post("/api/appeals", json=APPEAL)
    client.post("/api/appeals/a1/decision", json=DECISION | {"reason_code": "misread"})
    client.post("/api/decisions", json=REVIEW | {"reason_code": "by_rules"})
    manual = {"a": "no", "reason": "Не поздоровался", "by": "Специалист КК"}
    assert client.put("/api/dialogs/kz-1/answers/01", json=manual).status_code == 200

    response = client.get("/api/appeals/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["decisions"] == 2
    assert [(r["code"], r["cid"], r["status"], r["n"], r["share"]) for r in stats["reasons"]] == [
        ("misread", "04", "changed", 1, 0.5),
        ("by_rules", "04", "confirmed", 1, 0.5),
    ]
    modified = stats["modified"]
    assert (modified["pairs"], modified["changed"], modified["share"]) == (5, 2, 0.4)
    assert [(c["id"], c["pairs"], c["changed"], c["share"]) for c in modified["criteria"]] == [
        ("01", 2, 1, 0.5),
        ("04", 2, 1, 0.5),
        ("08", 1, 0, 0.0),
    ]
    assert [(g["key"], g["pairs"], g["changed"], g["share"]) for g in modified["langs"]] == [
        ("RU", 4, 1, 0.25),
        ("KZ", 1, 1, 1.0),
    ]
