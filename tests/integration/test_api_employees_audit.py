"""Сотрудники, текущий пользователь X-CQA-User, журнал действий и обзор работы через HTTP."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprint

CSV = "id;name;role;team\ne1;Алия Тестова;operator;Линия 1\ne2;Борис Пробный;reviewer;Контроль\n"
AS_ALIA = {"X-CQA-User": "e1"}
AS_BORIS = {"X-CQA-User": "e2"}
APPEAL = {
    "dlg": "p1-ru-003",
    "cid": "04",
    "ask": 10,
    "ev": [8],
    "comment": "Срок вывода назван, это существенная часть ответа.",
    "by": "Оператор",
}
DECISION = {"to": 10, "reason": "Срок вывода назван полностью", "reviewer": "Проверяющий"}
PROVIDER = {
    "label": "Локальная Qwen",
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "local-qwen",
    "where": "local",
    "key": "sk-audit-secret-42",
}


@pytest.fixture(autouse=True)
def scored(store: Store) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    c04 = next(c for c in checklist.criteria if c.id == "04")
    store.add_result("p1-ru-003", "04", 3, fingerprint(checklist, c04, "chat"), CriterionResult(a=5))


@pytest.fixture
def staff(client: TestClient) -> TestClient:
    assert client.post("/api/employees/import", content=CSV.encode()).json() == {"added": 2, "updated": 0}
    return client


def audit(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/audit", params=params)
    assert response.status_code == 200
    return list(response.json())


def test_employees_are_listed_edited_and_validated(staff: TestClient) -> None:
    assert [e["name"] for e in staff.get("/api/employees").json()] == ["Алия Тестова", "Борис Пробный"]
    body = {"name": "Галина Новая", "role": "manager", "team": "Руководство", "active": True}
    assert staff.put("/api/employees/e9", json=body).json() == {"id": "e9", **body}
    assert staff.put("/api/employees/e9", json={**body, "role": "boss"}).status_code == 422
    assert staff.put("/api/employees/e9", json={**body, "name": " "}).status_code == 422
    assert staff.post("/api/employees/import", content=b"e1;;qa;\n").status_code == 422


def test_me_is_the_employee_of_the_header_or_nobody(staff: TestClient) -> None:
    assert staff.get("/api/me", headers=AS_ALIA).json() == {
        "id": "e1",
        "name": "Алия Тестова",
        "role": "operator",
    }
    nobody = {"id": None, "name": "без входа", "role": ""}
    assert staff.get("/api/me").json() == nobody
    assert staff.get("/api/me", headers={"X-CQA-User": "ghost"}).json() == nobody
    staff.put(
        "/api/employees/e1", json={"name": "Алия Тестова", "role": "operator", "team": "", "active": False}
    )
    assert staff.get("/api/me", headers=AS_ALIA).json() == nobody


def test_without_header_appeal_keeps_the_role_sign_and_is_logged_under_it(client: TestClient) -> None:
    appeal = client.post("/api/appeals", json=APPEAL).json()
    decided = client.post(f"/api/appeals/{appeal['id']}/decision", json=DECISION).json()

    assert (appeal["by"], decided["reviewer"]) == ("Оператор", "Проверяющий")
    entries = audit(client)
    assert [(e["action"], e["actor_id"], e["actor_name"]) for e in entries] == [
        ("appeal.decide", None, "Проверяющий"),
        ("appeal.file", None, "Оператор"),
    ]
    assert entries[0]["target_type"] == "appeal" and entries[0]["target_id"] == appeal["id"]


def test_with_header_records_carry_the_employee(staff: TestClient) -> None:
    appeal = staff.post("/api/appeals", json=APPEAL, headers=AS_ALIA).json()
    decided = staff.post(f"/api/appeals/{appeal['id']}/decision", json=DECISION, headers=AS_BORIS).json()

    assert (appeal["by"], decided["reviewer"]) == ("Алия Тестова", "Борис Пробный")
    assert [(e["actor_id"], e["role"]) for e in audit(staff, action="appeal.decide")] == [("e2", "reviewer")]
    people = {p["id"]: p for p in staff.get("/api/overview").json()["employees"]}
    assert people["e1"]["appeals_filed"] == 1 and people["e2"]["decisions"] == 1
    assert people["e2"]["median_decision_min"] == 0.0


def test_every_mutation_and_export_lands_in_the_audit(staff: TestClient) -> None:
    calls = [
        staff.post(
            "/api/dialogs/text", json={"title": "Чат", "ch": "chat", "text": "Оператор: Здравствуйте"}
        ),
        staff.post("/api/datasets/upload", content=b"[]"),
        staff.post("/api/dialogs/p1-ru-003/reviewed", json={"reviewed": True}),
        staff.put("/api/owners", json={"срок": "Сервис"}),
        staff.get("/api/report?format=md"),
        staff.get("/api/checklist/export?format=csv"),
        staff.get("/api/audit?format=csv"),
    ]
    assert [c.status_code for c in calls] == [200] * 7

    actions = [e["action"] for e in audit(staff)]
    assert actions[:7] == [
        "export",
        "export",
        "export",
        "owners.save",
        "dialog.reviewed",
        "dataset.upload",
        "dataset.paste",
    ]
    assert actions[-1] == "employee.import"
    assert staff.get("/api/audit?format=csv").headers["content-type"].startswith("text/csv")


def test_provider_key_never_reaches_the_audit(staff: TestClient) -> None:
    assert staff.put("/api/providers/local", json=PROVIDER, headers=AS_BORIS).status_code == 200
    config = {
        "llm_provider": "local",
        "anonymize": False,
        "jev_api_key": "jev-audit-77",
        "allow_real_data": True,
    }
    staff.put("/api/config", json=config)

    text = staff.get("/api/audit?format=csv").text + str(audit(staff))
    assert "sk-audit-secret-42" not in text and "jev-audit-77" not in text
    entry = audit(staff, action="provider.save")[0]
    assert entry["target_id"] == "local" and entry["details"]["model"] == "local-qwen"


def test_overview_has_workload_and_teams(staff: TestClient) -> None:
    out = staff.get("/api/overview").json()
    assert out["workload"] == {"pending_appeals": 0, "needs_review": 0, "unreviewed": 2}
    assert {t["team"] for t in out["teams"]} == {"Линия 1", "Контроль"}
