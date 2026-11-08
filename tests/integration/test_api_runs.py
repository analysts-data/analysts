"""Runs through the API. The client is a context manager: one event loop keeps the run task alive."""

import asyncio
import sqlite3
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource


def _client(settings: Settings, conn: sqlite3.Connection, evaluator: FakeEvaluator | None) -> TestClient:
    return TestClient(create_app(settings, source=FakeSource(), evaluator=evaluator, conn=conn))


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


def _wait(client: TestClient, run_id: int) -> dict[str, Any]:
    _until(lambda: client.get(f"/api/runs/{run_id}").json()["status"] != "running")
    return client.get(f"/api/runs/{run_id}").json()


def _run(client: TestClient, **body: Any) -> int:
    response = client.post("/api/runs", json={"dialogs": None, "criteria": None, **body})
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert isinstance(run_id, int)
    return run_id


def _res(client: TestClient) -> dict[str, dict[str, Any]]:
    return {d["id"]: d["res"] for d in client.get("/api/state").json()["dialogs"]}


def test_whole_set_is_evaluated_with_progress(api: TestClient) -> None:
    assert _wait(api, _run(api)) == {
        "done": 16,
        "total": 16,
        "cost": pytest.approx(0.016),
        "calls": 16,
        "eta_s": 0,
        "errors": [],
        "status": "done",
    }
    assert {d: len(r) for d, r in _res(api).items()} == {"call-024": 8, "p1-ru-003": 8}


def test_ready_answers_are_not_evaluated_again(api: TestClient, evaluator: FakeEvaluator) -> None:
    _wait(api, _run(api))
    calls = evaluator.calls
    progress = api.get(f"/api/runs/{_run(api)}").json()
    assert (progress["total"], progress["status"]) == (0, "done")
    assert evaluator.calls == calls


def test_failed_dialog_does_not_stop_the_rest(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    with _client(settings, conn, FakeEvaluator(fail_on={"p1-ru-003"})) as client:
        progress = _wait(client, _run(client))
        assert (progress["done"], progress["errors"]) == (16, ["p1-ru-003: timeout"])
        assert {d: len(r) for d, r in _res(client).items()} == {"call-024": 8, "p1-ru-003": 0}


def test_dialog_cost_of_the_last_evaluation_is_in_the_state(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    with _client(settings, conn, FakeEvaluator(verifier_calls=1, verifier_usd=0.0002)) as client:
        _wait(client, _run(client, dialogs=["call-024"]))
        dialogs = {d["id"]: d for d in client.get("/api/state").json()["dialogs"]}
    cost = dialogs["call-024"]["cost"]
    assert (cost["calls"], cost["verifier_calls"], isinstance(cost["ms"], int)) == (8, 1, True)
    assert cost["usd"] == pytest.approx(0.0082, abs=1e-9)
    assert "cost" not in dialogs["p1-ru-003"]


def test_cancel_mid_run_then_resume_where_it_stopped(store: Store, conn: sqlite3.Connection) -> None:
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    settings = Settings(_env_file=None, db_path=":memory:", llm_max_parallel=1)
    with _client(settings, conn, evaluator) as client:
        run_id = _run(client)
        _until(lambda: evaluator.order == ["call-024"])
        cancelled = client.post(f"/api/runs/{run_id}/cancel")
        assert (cancelled.status_code, cancelled.json()) == (200, {"status": "cancelled"})
        client.portal.call(gate.set)  # type: ignore[union-attr]  # the loop owns the event
        progress = _wait(client, run_id)
        assert (progress["status"], progress["done"]) == ("cancelled", 8)
        assert evaluator.order == ["call-024"]
        assert {d: len(r) for d, r in _res(client).items()} == {"call-024": 8, "p1-ru-003": 0}

        resumed = _wait(client, _run(client))
        assert (resumed["total"], resumed["status"]) == (8, "done")
        assert evaluator.order == ["call-024", "p1-ru-003"]


def test_second_run_while_one_is_active_is_409(
    store: Store, conn: sqlite3.Connection, settings: Settings
) -> None:
    gate = asyncio.Event()
    with _client(settings, conn, FakeEvaluator(gate=gate)) as client:
        run_id = _run(client)
        response = client.post("/api/runs", json={"dialogs": None, "criteria": None})
        assert (response.status_code, response.json()) == (
            409,
            {"detail": f"Запуск {run_id} ещё идёт", "run_id": run_id, "done": 0, "total": 16, "eta_s": None},
        )
        client.portal.call(gate.set)  # type: ignore[union-attr]
        assert _wait(client, run_id)["status"] == "done"


def test_cancel_of_finished_and_unknown_runs(api: TestClient) -> None:
    run_id = _run(api)
    _wait(api, run_id)
    finished = api.post(f"/api/runs/{run_id}/cancel")
    assert (finished.status_code, finished.json()) == (409, {"detail": f"Запуск {run_id} уже завершён: done"})
    unknown = api.post("/api/runs/999/cancel")
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "Запуск 999 не найден"})


def test_unknown_run_is_404(api: TestClient) -> None:
    response = api.get("/api/runs/999")
    assert (response.status_code, response.json()) == (404, {"detail": "Запуск 999 не найден"})


def test_unknown_dialogs_in_a_run_are_404(api: TestClient) -> None:
    response = api.post("/api/runs", json={"dialogs": ["nope"], "criteria": None})
    assert (response.status_code, response.json()) == (404, {"detail": "Диалоги не найдены: nope"})


def test_without_an_evaluator_runs_are_503(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    with _client(settings, conn, FakeEvaluator()) as client:
        client.app.state.runner = None  # type: ignore[attr-defined]  # create_app may wire a default evaluator
        response = client.post("/api/runs", json={"dialogs": None, "criteria": None})
    assert (response.status_code, response.json()) == (503, {"detail": "Оценка моделью не подключена"})
