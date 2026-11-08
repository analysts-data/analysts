"""Правила обработки через HTTP: сохранение, проверка на диалоге, ошибки по-русски."""

import sqlite3

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator

CALLS = {
    "id": "calls",
    "name": "Звонки",
    "match": {"ch": "call", "has_audio": True},
    "use": {"verifier": "jev"},
}


def _client(settings: Settings, conn: sqlite3.Connection) -> TestClient:
    return TestClient(create_app(settings, evaluator=FakeEvaluator(), conn=conn))


def test_explain_names_the_matching_rule_and_every_condition(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    assert client.put("/api/routing", json=[CALLS]).status_code == 200
    assert [r["id"] for r in client.get("/api/routing").json()] == ["calls", "default"]
    call = client.post("/api/routing/explain", json={"dialog_id": "call-024"}).json()
    assert call["rule"] == {"id": "calls", "name": "Звонки"} and call["use"]["verifier"] == "jev"
    chat = client.post("/api/routing/explain", json={"dialog_id": "p1-ru-003"}).json()
    assert chat["rule"]["id"] == "default"
    assert chat["rules"][0]["conditions"][0] == {
        "field": "ch",
        "ok": False,
        "text": "канал: чат — нужно звонок",
    }


def test_bad_rule_is_422_in_russian_with_the_field_and_nothing_changes(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    before = client.get("/api/routing").json()
    bad = client.put("/api/routing", json=[{**CALLS, "use": {"llm_provider": "nope"}}])
    assert bad.status_code == 422
    assert "правило 1 «Звонки» → use.llm_provider: нет провайдера «nope»" in bad.json()["detail"]
    assert client.get("/api/routing").json() == before
