"""Ручной ответ и режим оценки через HTTP: то, что интерфейс делает кнопками."""

import sqlite3

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, prototype_checklist

BOOL = next(c for c in prototype_checklist().criteria if c.type == "bool" and not c.na)
CONFIG = {
    "llm_base_url": "http://127.0.0.1:11434/v1",
    "llm_model": "local-qwen",
    "llm_profile": "plain",
    "llm_api_key": "sk-local",
    "data_where": "local",
    "anonymize": False,
    "verifier": None,
    "jev_api_key": "",
    "allow_real_data": True,
}


def _client(settings: Settings, conn: sqlite3.Connection) -> TestClient:
    return TestClient(create_app(settings, evaluator=FakeEvaluator(), conn=conn))


def test_manual_answer_shows_up_in_the_state(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    url = f"/api/dialogs/p1-ru-003/answers/{BOOL.id}"
    response = client.put(url, json={"a": "no", "reason": "Не поздоровался", "by": "Специалист КК"})
    assert response.status_code == 200
    assert response.json()["a"] == "no"
    dialog = next(d for d in client.get("/api/state").json()["dialogs"] if d["id"] == "p1-ru-003")
    assert dialog["res"][BOOL.id]["a"] == "no"
    assert client.put(url, json={"a": "maybe", "by": "КК"}).status_code == 422


def test_config_switches_the_mode_without_restart_and_survives_one(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    before = client.get("/api/config").json()
    assert before["llm_model"] == settings.llm_model and before["has_llm_key"] is False
    response = client.put("/api/config", json=CONFIG)
    assert response.status_code == 200
    assert response.json()["has_llm_key"] is True and "sk-local" not in response.text
    mode = client.get("/api/state").json()["mode"]
    assert (mode["where"], mode["anonymized"], mode["model"]) == ("local", False, "local-qwen")
    restarted = _client(settings, conn)
    assert restarted.get("/api/state").json()["mode"]["model"] == "local-qwen"
    assert restarted.get("/api/config").json()["allow_real_data"] is True


def test_bad_config_is_422_and_keeps_the_mode(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    response = client.put("/api/config", json={**CONFIG, "llm_profile": "nope"})
    assert response.status_code == 422
    assert client.get("/api/state").json()["mode"]["model"] == settings.llm_model


def test_config_switches_to_jev_only_and_the_mode_shows_jev(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    response = client.put("/api/config", json={**CONFIG, "evaluator": "jev"})
    assert response.status_code == 200 and response.json()["evaluator"] == "jev"
    mode = client.get("/api/state").json()["mode"]
    assert (mode["model"], mode["verifier"]) == ("jev-latest", None)
    assert client.put("/api/config", json={**CONFIG, "evaluator": "gpt"}).status_code == 422
