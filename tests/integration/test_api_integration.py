"""Integration API: one dialogue or a batch is saved, evaluated by the usual run and returned."""

import asyncio
import hashlib
import hmac
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.services import integration
from cqa.settings import Settings
from fakes import FIXTURES, FakeEvaluator

RECORDS = {
    r["conversation_id"]: r
    for r in json.loads((FIXTURES / "org_payload.json").read_text())["data"]["records"]
}
CHAT = RECORDS["syn-chat-ru"]
CALL = RECORDS["syn-call-hold"]
PASTE = {
    "title": "Жалоба",
    "ch": "chat",
    "text": "Клиент: Здравствуйте, карта не работает.\nОператор: Проверю.",
}
HOOK = "https://crm.test/hooks/cqa"


def _client(settings: Settings, conn: sqlite3.Connection, evaluator: FakeEvaluator | None) -> TestClient:
    """Real source (`build_source`): the record goes through the same ingest as «Загрузить JSON»."""
    return TestClient(create_app(settings, evaluator=evaluator, conn=conn))


@pytest.fixture
def api(
    settings: Settings, store: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> Iterator[TestClient]:
    with _client(settings, conn, evaluator) as client:
        yield client


def _until(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2
    while not check():
        assert time.monotonic() < deadline, "no progress within 2 seconds"
        time.sleep(0.01)


def _ids(client: TestClient) -> set[str]:
    return {d["id"] for d in client.get("/api/state").json()["dialogs"]}


def test_record_is_saved_evaluated_and_returned_in_one_call(api: TestClient) -> None:
    response = api.post("/api/evaluate", json=CHAT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["dialog_id"], body["total"], body["critical_flag"], body["errors"]) == (
        "syn-chat-ru",
        100.0,
        False,
        [],
    )
    assert isinstance(body["run_id"], int)
    assert len(body["criteria"]) == 8
    assert {"cid", "name", "a", "why"} <= set(body["criteria"][0])
    record = body["results_v1"]
    assert (record["conversation_id"], record["status"], record["score"]["final_score"]) == (
        "syn-chat-ru",
        "ok",
        100.0,
    )
    assert len(record["criteria"]) == 8


def test_repeated_record_is_not_saved_or_evaluated_twice(api: TestClient, evaluator: FakeEvaluator) -> None:
    first = api.post("/api/evaluate", json=CHAT).json()
    second = api.post("/api/evaluate", json={**CHAT, "transcript": CHAT["transcript"][:2]}).json()
    assert evaluator.calls == 1
    assert (second["dialog_id"], second["total"], len(second["criteria"])) == (
        "syn-chat-ru",
        first["total"],
        8,
    )


def test_pasted_text_is_evaluated_like_paste(api: TestClient) -> None:
    body = api.post("/api/evaluate", json=PASTE).json()
    assert (body["dialog_id"], len(body["criteria"])) == ("paste-1", 8)
    dialog = api.get("/api/dialogs/paste-1").json()["dialog"]
    assert dialog["title"] == "Жалоба"


def test_without_wait_the_answer_is_202_and_the_result_is_polled(api: TestClient) -> None:
    response = api.post("/api/evaluate?wait=false", json=CHAT)
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"dialog_id", "run_id"}
    _until(lambda: api.get(f"/api/runs/{body['run_id']}").json()["status"] == "done")
    got = api.get("/api/dialogs/syn-chat-ru").json()
    assert (got["dialog_id"], got["total"], got["critical_flag"], len(got["criteria"])) == (
        "syn-chat-ru",
        100.0,
        False,
        8,
    )
    assert got["results_v1"]["status"] == "ok"
    assert set(got["dialog"]["res"]) == {c["cid"] for c in got["criteria"]}


def test_evaluation_longer_than_the_wait_falls_back_to_202(
    settings: Settings, store: Store, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(integration, "WAIT_S", 0.05)
    gate = asyncio.Event()
    with _client(settings, conn, FakeEvaluator(gate=gate)) as client:
        response = client.post("/api/evaluate", json=CHAT)
        assert response.status_code == 202
        assert set(response.json()) == {"dialog_id", "run_id"}
        client.portal.call(gate.set)  # type: ignore[union-attr]  # the loop owns the event


def test_evaluate_while_a_run_is_active_is_409_and_saves_nothing(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    gate = asyncio.Event()
    with _client(settings, conn, FakeEvaluator(gate=gate)) as client:
        run_id = client.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"]
        response = client.post("/api/evaluate", json=CHAT)
        assert response.status_code == 409
        assert response.json() == {
            "detail": f"Запуск {run_id} ещё идёт",
            "run_id": run_id,
            "done": 0,
            "total": 16,
            "eta_s": None,
        }
        assert client.post("/api/evaluate/batch", json={"dialogs": [CHAT]}).status_code == 409
        assert "syn-chat-ru" not in _ids(client)
        client.portal.call(gate.set)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "body",
    [{"conversation_id": "x"}, {**PASTE, "text": "Клиент: алло"}, {**CHAT, "transcript": []}],
    ids=["neither-format", "paste-without-operator", "empty-transcript"],
)
def test_body_that_is_not_a_dialogue_is_422(api: TestClient, body: dict[str, Any]) -> None:
    assert api.post("/api/evaluate", json=body).status_code == 422


def test_batch_saves_every_dialogue_and_starts_one_run(api: TestClient) -> None:
    response = api.post("/api/evaluate/batch", json={"dialogs": [CHAT, RECORDS["syn-chat-kz"], PASTE]})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dialog_ids"] == ["syn-chat-ru", "syn-chat-kz", "paste-1"]
    _until(lambda: api.get(f"/api/runs/{body['run_id']}").json()["status"] == "done")
    assert api.get(f"/api/runs/{body['run_id']}").json()["total"] == 24
    assert all(len(api.get(f"/api/dialogs/{i}").json()["criteria"]) == 8 for i in body["dialog_ids"])


def test_batch_over_100_dialogues_is_422(api: TestClient) -> None:
    assert api.post("/api/evaluate/batch", json={"dialogs": [PASTE] * 101}).status_code == 422
    assert api.post("/api/evaluate/batch", json={"dialogs": []}).status_code == 422


def test_unknown_dialog_is_404(api: TestClient) -> None:
    response = api.get("/api/dialogs/nope")
    assert (response.status_code, response.json()) == (404, {"detail": "Диалог nope не найден"})


@respx.mock
def test_real_call_is_not_sent_to_a_live_model_without_permission(
    store: Store, conn: sqlite3.Connection
) -> None:
    live = Settings(
        _env_file=None,
        db_path=":memory:",
        llm_mode="live",
        llm_api_key="k",
        llm_base_url="https://llm.test/v1",
    )
    with _client(live, conn, None) as client:
        body = client.post("/api/evaluate", json=CALL).json()
    assert body["criteria"] == []
    assert body["errors"] and "CQA_ALLOW_REAL_DATA" in body["errors"][0]
    assert not respx.calls


def test_finished_run_posts_a_signed_webhook_without_dialogue_text(
    store: Store, conn: sqlite3.Connection
) -> None:
    hooked = Settings(_env_file=None, db_path=":memory:", webhook_url=HOOK, webhook_secret="s3cret")
    with respx.mock, _client(hooked, conn, FakeEvaluator()) as client:
        route = respx.post(HOOK).mock(return_value=httpx.Response(204))
        run_id = client.post("/api/evaluate", json=CHAT).json()["run_id"]
        _until(lambda: route.called)
    request = route.calls.last.request
    assert json.loads(request.content) == {
        "event": "run.finished",
        "run_id": run_id,
        "status": "done",
        "done": 8,
        "total": 8,
        "errors": [],
        "dialog_ids": ["syn-chat-ru"],
    }
    signature = hmac.new(b"s3cret", request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-CQA-Signature"] == f"sha256={signature}"


def test_webhook_failure_does_not_break_the_run(store: Store, conn: sqlite3.Connection) -> None:
    hooked = Settings(_env_file=None, db_path=":memory:", webhook_url=HOOK)
    with respx.mock, _client(hooked, conn, FakeEvaluator()) as client:
        route = respx.post(HOOK).mock(return_value=httpx.Response(500))
        body = client.post("/api/evaluate", json=CHAT).json()
        _until(lambda: route.called)
        assert client.get(f"/api/runs/{body['run_id']}").json()["status"] == "done"
        assert client.post("/api/evaluate", json=PASTE).status_code == 200


def _errors(response: httpx.Response) -> dict[str, dict[str, str]]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body["detail"], str) and body["detail"].startswith("Запрос не прошёл проверку")
    return {e["path"]: e for e in body["errors"]}


def test_422_names_each_field_with_a_russian_message_and_the_expected_format(api: TestClient) -> None:
    turn = {"timestamp": "00:00", "speaker": "client"}
    errors = _errors(
        api.post("/api/evaluate", json={"conversation_id": "x", "channel": 5, "transcript": [turn]})
    )
    assert set(errors) == {"channel", "language", "transcript.0.text"}
    assert errors["language"]["message"] == "обязательное поле"
    assert errors["channel"]["message"] == "нужна строка"
    assert errors["transcript.0.text"]["expected"]


def test_422_for_a_body_of_neither_format_shows_both_formats(api: TestClient) -> None:
    [error] = _errors(api.post("/api/evaluate", json={"hello": 1})).values()
    assert error["path"] == ""
    assert "conversation_id" in error["expected"] and "text" in error["expected"]


def test_422_in_a_batch_points_at_the_item(api: TestClient) -> None:
    errors = _errors(api.post("/api/evaluate/batch", json={"dialogs": [CHAT, {"text": "Оператор: да"}]}))
    assert set(errors) == {"dialogs.1.ch"}
    assert "chat" in errors["dialogs.1.ch"]["expected"]


def test_same_idempotency_key_returns_the_same_answer_without_a_second_evaluation(
    api: TestClient, evaluator: FakeEvaluator
) -> None:
    key = {"Idempotency-Key": "crm-42"}
    first = api.post("/api/evaluate", json=PASTE, headers=key)
    second = api.post("/api/evaluate", json=PASTE, headers=key)
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json() == first.json()
    assert evaluator.calls == 1 and "paste-2" not in _ids(api)
    assert api.post("/api/evaluate", json=PASTE).json()["dialog_id"] == "paste-2"  # without a key — a new one


def test_idempotency_key_with_another_body_is_422(api: TestClient) -> None:
    key = {"Idempotency-Key": "crm-43"}
    api.post("/api/evaluate", json=PASTE, headers=key)
    response = api.post("/api/evaluate", json={**PASTE, "title": "Другое"}, headers=key)
    assert response.status_code == 422
    assert "Idempotency-Key" in response.json()["detail"]


def test_same_idempotency_key_on_a_batch_starts_one_run(api: TestClient) -> None:
    key = {"Idempotency-Key": "batch-1"}
    first = api.post("/api/evaluate/batch", json={"dialogs": [PASTE]}, headers=key).json()
    _until(lambda: api.get(f"/api/runs/{first['run_id']}").json()["status"] == "done")
    second = api.post("/api/evaluate/batch", json={"dialogs": [PASTE]}, headers=key)
    assert (second.status_code, second.json()) == (202, first)


def test_repeat_of_a_key_still_in_progress_is_409(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    gate = asyncio.Event()
    key = {"Idempotency-Key": "slow"}
    with _client(settings, conn, FakeEvaluator(gate=gate)) as client:
        first: list[httpx.Response] = []
        thread = threading.Thread(
            target=lambda: first.append(client.post("/api/evaluate", json=PASTE, headers=key))
        )
        thread.start()
        _until(lambda: "paste-1" in _ids(client))
        response = client.post("/api/evaluate", json=PASTE, headers=key)
        assert response.status_code == 409
        assert "Idempotency-Key" in response.json()["detail"]
        client.portal.call(gate.set)  # type: ignore[union-attr]
        thread.join()
    assert first[0].status_code == 200


def test_run_status_shows_each_dialogue(store: Store, conn: sqlite3.Connection) -> None:
    gate = asyncio.Event()
    one = Settings(_env_file=None, db_path=":memory:", llm_max_parallel=1)
    with _client(one, conn, FakeEvaluator(gate=gate, fail_on={"syn-chat-kz"})) as client:
        run_id = client.post("/api/evaluate/batch", json={"dialogs": [CHAT, RECORDS["syn-chat-kz"]]}).json()[
            "run_id"
        ]
        _until(
            lambda: client.get(f"/api/runs/{run_id}/dialogs").json()["dialogs"][0]["status"] == "evaluating"
        )
        status = client.get(f"/api/runs/{run_id}/dialogs").json()
        assert (status["run_id"], status["status"], status["total"]) == (run_id, "running", 16)
        assert [(d["dialog_id"], d["status"], d["done"], d["total"]) for d in status["dialogs"]] == [
            ("syn-chat-ru", "evaluating", 0, 8),
            ("syn-chat-kz", "queued", 0, 8),
        ]
        client.portal.call(gate.set)  # type: ignore[union-attr]
        _until(lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "done")
        status = client.get(f"/api/runs/{run_id}/dialogs").json()
    assert [(d["status"], d["done"], d["error"]) for d in status["dialogs"]] == [
        ("done", 8, None),
        ("error", 0, "syn-chat-kz: timeout"),
    ]


def test_status_of_an_unknown_run_is_404(api: TestClient) -> None:
    assert api.get("/api/runs/999/dialogs").status_code == 404


def test_results_export_is_the_organisers_json_1_0_for_the_chosen_dialogues(api: TestClient) -> None:
    api.post("/api/evaluate", json=CHAT)
    doc = api.get("/api/results", params=[("ids", "syn-chat-ru"), ("ids", "nope")]).json()
    assert (doc["schema_version"], doc["team_name"]) == ("1.0", "analysts")
    assert doc["model"] == {"mode": "external_api", "name": "qwen3-6"}
    assert [(r["conversation_id"], r["status"]) for r in doc["results"]] == [
        ("syn-chat-ru", "ok"),
        ("nope", "error"),
    ]
    every = api.get("/api/results").json()["results"]
    assert {r["conversation_id"] for r in every} == {"call-024", "p1-ru-003", "syn-chat-ru"}
