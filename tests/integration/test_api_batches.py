"""Batch jobs through the API with a fake evaluator; the client context manager runs the queue."""

import asyncio
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.services.batches import RESTART_NOTE
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource


def _client(conn: sqlite3.Connection, evaluator: FakeEvaluator, **settings: Any) -> TestClient:
    s = Settings(_env_file=None, db_path=":memory:", **settings)
    return TestClient(create_app(s, source=FakeSource(), evaluator=evaluator, conn=conn))


def _until(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not check():
        assert time.monotonic() < deadline, "no progress within 5 seconds"
        time.sleep(0.01)


def _job(client: TestClient, job_id: int) -> dict[str, Any]:
    response = client.get(f"/api/batches/{job_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_job_runs_to_the_end_with_batches_eta_and_rate_limit(store: Store, conn: sqlite3.Connection) -> None:
    with _client(conn, FakeEvaluator(), llm_rpm=60, llm_max_parallel=3) as client:
        created = client.post("/api/batches", json={"filter": {}, "batch_size": 1, "priority": "high"})
        assert created.status_code == 200, created.text
        job_id = created.json()["id"]
        _until(lambda: _job(client, job_id)["status"] == "done")
        job = _job(client, job_id)
        listed = client.get("/api/batches").json()
    assert (job["total"], job["done"], job["errors"], job["pending"], job["eta_s"]) == (2, 2, 0, 0, None)
    assert [(b["no"], b["n"], b["done"]) for b in job["batches"]] == [(1, 1, 1), (2, 1, 1)]
    assert job["eta_basis"] == "по скорости последних 2 батчей"
    assert job["rate_limit"] == {"rpm": 60, "parallel": 3}
    assert listed["rate_limit"] == {"rpm": 60, "parallel": 3}
    assert [j["id"] for j in listed["jobs"]] == [job_id]
    assert "batches" not in listed["jobs"][0]


def test_pause_resume_cancel_and_retry_through_the_api(store: Store, conn: sqlite3.Connection) -> None:
    gate = asyncio.Event()
    with _client(conn, FakeEvaluator(gate=gate)) as client:
        job_id = client.post(
            "/api/batches", json={"dialogs": ["call-024", "p1-ru-003"], "batch_size": 1}
        ).json()["id"]
        _until(lambda: _job(client, job_id)["status"] == "running")
        assert client.post(f"/api/batches/{job_id}/pause").json()["status"] == "paused"
        client.portal.call(gate.set)  # type: ignore[union-attr]
        _until(lambda: _job(client, job_id)["done"] == 1)
        assert _job(client, job_id)["status"] == "paused"  # second batch waits
        assert client.post(f"/api/batches/{job_id}/resume").json()["status"] == "queued"
        _until(lambda: _job(client, job_id)["status"] == "done")
        response = client.post(f"/api/batches/{job_id}/cancel")
        assert (response.status_code, response.json()) == (
            409,
            {"detail": f"Задание {job_id} в статусе done: cancel недоступно"},
        )
        response = client.post(f"/api/batches/{job_id}/retry")
        assert (response.status_code, response.json()) == (
            409,
            {"detail": f"В задании {job_id} нет диалогов с ошибкой"},
        )


def test_server_restart_leaves_the_running_job_paused_with_a_note(
    store: Store, conn: sqlite3.Connection
) -> None:
    with _client(conn, FakeEvaluator(gate=asyncio.Event())) as client:
        job_id = client.post("/api/batches", json={"filter": {}, "batch_size": 1}).json()["id"]
        _until(lambda: _job(client, job_id)["status"] == "running")
    evaluator = FakeEvaluator()
    with _client(conn, evaluator) as client:
        job = _job(client, job_id)
        assert (job["status"], job["note"], job["pending"]) == ("paused", RESTART_NOTE, 2)
        time.sleep(0.05)
        assert evaluator.calls == 0  # no silent auto-resume
        client.post(f"/api/batches/{job_id}/resume")
        _until(lambda: _job(client, job_id)["status"] == "done")
        assert _job(client, job_id)["note"] is None
