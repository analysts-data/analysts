"""Маркеры и алерты через API: каталог, ручные маркеры, правила, оценка, статусы, вебхук."""

import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprint
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource

FLAG = {"insult": False, "paid": True, "leak": False}
HOOK = "https://hooks.test/cqa"


@pytest.fixture(autouse=True)
def results(store: Store) -> None:
    """p1-ru-003: грубое нарушение (paid) в реплике 4; call-024: 04 = 15 при расхождении с 10."""
    checklist = store.current_checklist()
    assert checklist is not None
    c04 = next(c for c in checklist.criteria if c.id == "04")
    c08 = next(c for c in checklist.criteria if c.id == "08")
    store.add_result(
        "p1-ru-003", "08", 3, fingerprint(checklist, c08, "chat"), CriterionResult(a=FLAG, ev=[4])
    )
    store.add_result("call-024", "04", 3, fingerprint(checklist, c04, "call"), CriterionResult(a=15, alt=10))


def dialog(client: TestClient, dialog_id: str) -> dict[str, Any]:
    return next(d for d in client.get("/api/state").json()["dialogs"] if d["id"] == dialog_id)


def evaluate(client: TestClient) -> list[dict[str, Any]]:
    response = client.post("/api/alerts/evaluate")
    assert response.status_code == 200, response.text
    created: list[dict[str, Any]] = response.json()["created"]
    return created


# --- маркеры ---


def test_state_dialogs_carry_auto_markers_with_basis(client: TestClient) -> None:
    markers = dialog(client, "p1-ru-003")["markers"]

    gross = next(m for m in markers if m["k"] == "gross")
    assert gross["auto"] is True and gross["label"] == "Грубое нарушение"
    assert gross["basis"]["lines"] == [4] and gross["basis"]["why"].startswith("Почему: ")
    assert {m["k"] for m in dialog(client, "call-024")["markers"]} >= {"no_next_step", "needs_review"}


def test_catalog_has_defaults_and_is_editable_with_russian_validation(client: TestClient) -> None:
    assert "Жалоба" in client.get("/api/markers/catalog").json()

    assert client.put("/api/markers/catalog", json=["Жалоба", "Спор"]).json() == ["Жалоба", "Спор"]
    assert client.get("/api/markers/catalog").json() == ["Жалоба", "Спор"]
    bad = client.put("/api/markers/catalog", json=["Жалоба", "Жалоба", " "])
    assert bad.status_code == 422
    assert {tuple(e["loc"]) for e in bad.json()["detail"]} == {("body", 1), ("body", 2)}


def test_manual_markers_are_added_and_removed_with_actor_from_header(client: TestClient) -> None:
    response = client.put(
        "/api/dialogs/call-024/markers",
        json={"add": ["Жалоба", "VIP-клиент"], "remove": []},
        headers={"X-CQA-User": "%D0%90%D0%BD%D0%BD%D0%B0"},  # «Анна» в percent-encoding
    )

    assert response.status_code == 200, response.text
    manual = [m for m in response.json()["markers"] if not m["auto"]]
    assert [(m["label"], m["by"]) for m in manual] == [("Жалоба", "Анна"), ("VIP-клиент", "Анна")]
    client.put("/api/dialogs/call-024/markers", json={"add": [], "remove": ["VIP-клиент"]})
    assert [m["label"] for m in dialog(client, "call-024")["markers"] if not m["auto"]] == ["Жалоба"]


def test_marker_outside_catalog_is_422_and_unknown_dialog_404(client: TestClient) -> None:
    bad = client.put("/api/dialogs/call-024/markers", json={"add": ["Нет такого"], "remove": []})
    assert bad.status_code == 422 and "Нет такого" in bad.json()["detail"]
    assert client.put("/api/dialogs/nope/markers", json={"add": [], "remove": []}).status_code == 404


# --- правила ---


def test_rules_default_and_put_validates_fields_in_russian(client: TestClient) -> None:
    rules = client.get("/api/alerts/rules").json()
    assert {r["kind"] for r in rules} == {
        "gross_error", "low_total", "operator_avg", "no_next_step_share",
        "raised_tone", "appeal_overdue", "run_errors", "marker", "long_silence",
    }  # fmt: skip
    assert all(r["why"] for r in rules)

    bad = dict(rules[1], params={"threshold": 500})
    response = client.put("/api/alerts/rules", json=[bad])
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", 0, "params", "threshold"]
    assert "от 0 до 100" in response.json()["detail"][0]["msg"]

    low = dict(rules[1], params={"threshold": 99})
    assert client.put("/api/alerts/rules", json=[low]).json() == [low]
    assert client.get("/api/alerts/rules").json() == [low]
    assert (
        next(m for m in dialog(client, "call-024")["markers"] if m["k"] == "low_total")["basis"]["rule"]
        == low["id"]
    )


# --- алерты ---


def test_evaluate_creates_alerts_once_per_rule_and_target(client: TestClient) -> None:
    created = evaluate(client)

    gross = next(a for a in created if a["rule_id"] == "gross")
    assert gross["target_type"] == "dialog" and gross["target_id"] == "p1-ru-003"
    assert gross["severity"] == "critical" and gross["status"] == "new"
    assert gross["basis"]["rule"] == "gross" and gross["basis"]["lines"] == [4]
    assert evaluate(client) == []


def test_alert_list_filters_and_counts_for_the_bell(client: TestClient) -> None:
    created = evaluate(client)

    body = client.get("/api/alerts").json()
    assert len(body["alerts"]) == len(created)
    assert body["counts"]["new"] == len(created) and body["counts"]["critical"] >= 1
    critical = client.get("/api/alerts", params={"severity": "critical"}).json()["alerts"]
    assert critical and all(a["severity"] == "critical" for a in critical)
    assert client.get("/api/alerts", params={"status": "resolved"}).json()["alerts"] == []
    assert client.get("/api/alerts", params={"status": "bogus"}).status_code == 422


def test_ack_resolve_and_assignee_record_who_and_when(client: TestClient) -> None:
    alert_id = evaluate(client)[0]["id"]

    acked = client.post(f"/api/alerts/{alert_id}/ack", json={"by": "Анна"}).json()
    assert acked["status"] == "ack" and acked["acked_by"] == "Анна" and acked["acked_at"]
    assigned = client.put(f"/api/alerts/{alert_id}/assignee", json={"assignee": "Борис", "by": "Анна"}).json()
    assert assigned["assignee"] == "Борис"
    assert client.post(f"/api/alerts/{alert_id}/resolve", json={"note": "", "by": "Анна"}).status_code == 422
    done = client.post(
        f"/api/alerts/{alert_id}/resolve", json={"note": "Разобрано с оператором", "by": "Борис"}
    )
    assert done.json()["status"] == "resolved" and done.json()["resolved_by"] == "Борис"
    assert done.json()["note"] == "Разобрано с оператором" and done.json()["resolved_at"]


def test_wrong_transitions_are_409_and_unknown_alert_404(client: TestClient) -> None:
    alert_id = evaluate(client)[0]["id"]
    client.post(f"/api/alerts/{alert_id}/resolve", json={"note": "Ложное срабатывание"})

    again = client.post(f"/api/alerts/{alert_id}/ack", json={})
    assert again.status_code == 409 and "закрыт" in again.json()["detail"]
    assert client.post(f"/api/alerts/{alert_id}/resolve", json={"note": "ещё раз"}).status_code == 409
    assert client.put(f"/api/alerts/{alert_id}/assignee", json={"assignee": "Х"}).status_code == 409
    assert client.post("/api/alerts/999/ack", json={}).status_code == 404


def test_marker_change_evaluates_alerts(client: TestClient) -> None:
    client.put("/api/dialogs/call-024/markers", json={"add": ["Жалоба"], "remove": []})

    alerts = client.get("/api/alerts").json()["alerts"]
    complaint = next(a for a in alerts if a["rule_id"] == "complaint")
    assert complaint["target_id"] == "call-024" and complaint["basis"]["marker"] == "Жалоба"


def test_appeal_filing_evaluates_alerts(client: TestClient) -> None:
    appeal = {
        "dlg": "call-024",
        "cid": "04",
        "ask": 20,
        "ev": [],
        "comment": "Срок назван полностью",
        "by": "Оп",
    }
    assert client.post("/api/appeals", json=appeal).status_code == 200

    assert any(a["rule_id"] == "gross" for a in client.get("/api/alerts").json()["alerts"])


# --- запуск и вебхук ---


@pytest.fixture
def api(settings: Settings, store: Store, conn: sqlite3.Connection) -> Iterator[TestClient]:
    evaluator = FakeEvaluator(fail_on={"call-024"})
    with TestClient(create_app(settings, source=FakeSource(), evaluator=evaluator, conn=conn)) as client:
        yield client


def test_finished_run_with_errors_raises_alert(api: TestClient) -> None:
    run_id = api.post("/api/runs", json={"dialogs": ["call-024"], "criteria": ["01"]}).json()["run_id"]

    deadline = time.monotonic() + 2
    while not any(a["rule_id"] == "run-errors" for a in api.get("/api/alerts").json()["alerts"]):
        assert time.monotonic() < deadline, "нет алерта об ошибках запуска"
        time.sleep(0.01)
    alert = next(a for a in api.get("/api/alerts").json()["alerts"] if a["rule_id"] == "run-errors")
    assert alert["target_id"] == str(run_id) and alert["basis"]["dialogs"] == ["call-024"]


@respx.mock
def test_new_alerts_go_to_webhook_signed_without_dialogue_text(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    route = respx.post(HOOK).mock(return_value=httpx.Response(204))
    hooked = settings.model_copy(update={"webhook_url": HOOK, "webhook_secret": SecretStr("s3cret")})
    client = TestClient(create_app(hooked, source=FakeSource(), evaluator=FakeEvaluator(), conn=conn))

    created = evaluate(client)

    assert route.call_count == len(created) > 0
    request = route.calls[0].request
    body = request.content
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert request.headers["X-CQA-Signature"] == expected
    event = json.loads(body)
    assert event["event"] == "alert.created" and event["data"]["id"] == created[0]["id"]
    texts = [ln.text for d in store.list_dialogs() for ln in d.lines or [] if getattr(ln, "text", "")]
    assert not [t for t in texts if len(t) > 15 and t in body.decode()]


@respx.mock
def test_webhook_failure_does_not_break_evaluation(settings: Settings, conn: sqlite3.Connection) -> None:
    respx.post(HOOK).mock(side_effect=httpx.ConnectError("down"))
    hooked = settings.model_copy(update={"webhook_url": HOOK})
    client = TestClient(create_app(hooked, source=FakeSource(), evaluator=FakeEvaluator(), conn=conn))

    assert evaluate(client)
