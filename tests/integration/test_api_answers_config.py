"""Ручной ответ и режим оценки через HTTP: то, что интерфейс делает кнопками."""

import json
import sqlite3

import respx
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, prototype_checklist

BOOL = next(c for c in prototype_checklist().criteria if c.type == "bool" and not c.na)
LOCAL = {
    "label": "Локальная Qwen",
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "local-qwen",
    "profile": "plain",
    "where": "local",
    "key": "sk-local",
}
CONFIG = {
    "llm_provider": "local",
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
    assert [p["id"] for p in before["providers"]] == ["env"]
    added = client.put("/api/providers/local", json=LOCAL)
    assert added.status_code == 200 and "sk-local" not in added.text
    assert added.json()["providers"][1] == {
        "id": "local",
        **{k: v for k, v in LOCAL.items() if k != "key"},
        "has_key": True,
    }
    response = client.put("/api/config", json=CONFIG)
    assert response.status_code == 200
    assert response.json()["has_llm_key"] is True and "sk-local" not in response.text
    mode = client.get("/api/state").json()["mode"]
    assert (mode["where"], mode["anonymized"], mode["model"]) == ("local", False, "local-qwen")
    restarted = _client(settings, conn)
    assert restarted.get("/api/state").json()["mode"]["model"] == "local-qwen"
    assert restarted.get("/api/config").json()["allow_real_data"] is True


def test_second_opinion_from_a_provider_shows_in_the_mode(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    client.put("/api/providers/local", json=LOCAL)
    response = client.put("/api/config", json={**CONFIG, "llm_provider": "env", "verifier": "local"})
    assert response.status_code == 200
    assert client.get("/api/state").json()["mode"]["verifier"] == "local"
    assert client.delete("/api/providers/local").status_code == 409
    client.put("/api/config", json={**CONFIG, "llm_provider": "env"})
    deleted = client.delete("/api/providers/local")
    assert deleted.status_code == 200 and [p["id"] for p in deleted.json()["providers"]] == ["env"]
    assert client.delete("/api/providers/local").status_code == 404


def test_bad_config_is_422_and_keeps_the_mode(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    assert client.put("/api/providers/local", json={**LOCAL, "profile": "nope"}).status_code == 422
    assert client.put("/api/config", json=CONFIG).status_code == 422
    assert client.get("/api/state").json()["mode"]["model"] == settings.llm_model


def test_check_sends_one_synthetic_request_and_reports_the_result(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn)
    client.put("/api/providers/local", json=LOCAL)
    with respx.mock(assert_all_called=True) as net:
        route = net.post("http://127.0.0.1:11434/v1/chat/completions")
        route.respond(200, json={"choices": [{"message": {"content": "да"}}]})
        ok = client.post("/api/providers/local/check").json()
        route.respond(401, json={"error": "bad key"})
        bad = client.post("/api/providers/local/check").json()
    sent = json.loads(route.calls[0].request.content)
    assert (sent["model"], sent["max_tokens"], route.calls[0].request.headers["authorization"]) == (
        "local-qwen",
        1,
        "Bearer sk-local",
    )
    assert (ok["ok"], ok["error"], bad["ok"]) == (True, None, False)
    assert "401" in bad["error"] and isinstance(ok["ms"], int)
    assert client.post("/api/providers/nope/check").status_code == 404
