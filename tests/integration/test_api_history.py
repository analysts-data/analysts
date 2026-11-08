"""Повторная проверка, история оценок, возврат прежней оценки, список и сравнение запусков через API."""

import sqlite3
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource, prototype_dialogs

PROTO = {d.id: d.res for d in prototype_dialogs()}


@pytest.fixture
def api(
    settings: Settings, store: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> Iterator[TestClient]:
    with TestClient(create_app(settings, source=FakeSource(), evaluator=evaluator, conn=conn)) as client:
        yield client


def _until(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2
    while not check():
        assert time.monotonic() < deadline, "no progress within 2 seconds"
        time.sleep(0.01)


def _run(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/runs", json={"dialogs": None, "criteria": None, **body})
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    _until(lambda: client.get(f"/api/runs/{run_id}").json()["status"] != "running")
    return {"id": run_id, **client.get(f"/api/runs/{run_id}").json()}


def test_forced_run_re_evaluates_and_history_keeps_both_answers(api: TestClient) -> None:
    first = _run(api)
    assert _run(api)["total"] == 0  # без force готовые ответы не трогаются
    again = _run(api, force=True, dialogs=["call-024"])
    assert (again["total"], again["skipped"], again["status"]) == (8, 0, "done")

    rows = api.get("/api/dialogs/call-024/history").json()["04"]

    assert [(r["run_id"], r["current"], r["stale"]) for r in rows] == [
        (again["id"], True, False),
        (first["id"], False, False),
    ]
    assert set(rows[0]) == {
        "id",
        "created",
        "run_id",
        "version",
        "model",
        "a",
        "why",
        "ev",
        "current",
        "stale",
        "shadow",
        "override",
    }


def test_forced_run_skips_a_manual_answer_and_counts_it(api: TestClient) -> None:
    _run(api, dialogs=["call-024"])
    manual = {"a": "no", "reason": "", "by": "Специалист КК"}
    assert api.put("/api/dialogs/call-024/answers/01", json=manual).status_code == 200

    again = _run(api, force=True, dialogs=["call-024"])

    assert (again["total"], again["skipped"]) == (7, 1)
    state = {d["id"]: d for d in api.get("/api/state").json()["dialogs"]}
    assert state["call-024"]["res"]["01"]["model"] == "вручную"


def test_runs_list_and_comparison_of_two_models(api: TestClient) -> None:
    first = _run(api, dialogs=["call-024"])
    other = {
        **PROTO,
        "call-024": {**PROTO["call-024"], "04": PROTO["call-024"]["04"].model_copy(update={"a": 0})},
    }
    api.app.state.runner.use(FakeEvaluator(res=other))  # type: ignore[attr-defined]
    second = _run(api, dialogs=["call-024"], force=True)

    runs = api.get("/api/runs").json()
    assert [(r["id"], r["force"], r["model"], r["total"], r["done"]) for r in runs] == [
        (second["id"], True, "qwen3-6", 8, 8),
        (first["id"], False, "qwen3-6", 8, 8),
    ]
    assert set(runs[0]) == {"id", "created", "status", "model", "checklist_version", "total", "done", "cost",
                            "errors_count", "force", "skipped", "apply", "override"}  # fmt: skip

    got = api.get(f"/api/runs/compare?a={first['id']}&b={second['id']}").json()

    assert (got["a"], got["b"], got["pairs"], got["agree"]) == (first["id"], second["id"], 8, 7 / 8)
    assert got["diffs"] == [{"dialog": "call-024", "cid": "04", "a": PROTO["call-024"]["04"].a, "b": 0}]
    scale = next(c for c in got["criteria"] if c["cid"] == "04")
    assert scale["agree"] == 0.0 and scale["mean_step_diff"] > 0


def test_compare_with_an_unknown_run_is_404(api: TestClient) -> None:
    first = _run(api)
    response = api.get(f"/api/runs/compare?a={first['id']}&b=999")
    assert (response.status_code, response.json()) == (404, {"detail": "Запуск 999 не найден"})


def test_restore_makes_a_past_answer_current_again(api: TestClient) -> None:
    _run(api, dialogs=["call-024"])
    api.put("/api/dialogs/call-024/answers/01", json={"a": "no", "reason": "", "by": "Специалист КК"})
    model_row = api.get("/api/dialogs/call-024/history").json()["01"][1]

    response = api.post(f"/api/results/{model_row['id']}/restore")

    assert response.status_code == 200
    assert (response.json()["a"], response.json().get("model")) == (model_row["a"], model_row["model"])
    newest = api.get("/api/dialogs/call-024/history").json()["01"][0]
    assert (newest["a"], newest["run_id"], newest["current"]) == (model_row["a"], model_row["run_id"], True)


def test_restore_while_an_appeal_is_pending_is_409(api: TestClient) -> None:
    _run(api, dialogs=["p1-ru-003"])
    _run(api, dialogs=["p1-ru-003"], force=True, criteria=["01"])
    old = api.get("/api/dialogs/p1-ru-003/history").json()["01"][1]
    ask = "no" if old["a"] == "yes" else "yes"
    appeal = {
        "dlg": "p1-ru-003",
        "cid": "01",
        "ask": ask,
        "ev": [],
        "comment": "Оператор не согласен",
        "by": "О",
    }
    assert api.post("/api/appeals", json=appeal).status_code == 200

    response = api.post(f"/api/results/{old['id']}/restore")

    assert response.status_code == 409 and "апелляция" in response.json()["detail"]


def test_unknown_dialog_history_and_unknown_result_are_404(api: TestClient) -> None:
    assert api.get("/api/dialogs/nope/history").status_code == 404
    assert api.post("/api/results/999/restore").status_code == 404


def test_state_tells_each_dialog_status_in_its_latest_run(api: TestClient) -> None:
    def statuses() -> dict[str, Any]:
        return {d["id"]: d["eval_status"] for d in api.get("/api/state").json()["dialogs"]}

    assert statuses() == {"call-024": None, "p1-ru-003": None}
    run = _run(api, dialogs=["call-024"])
    assert statuses() == {
        "call-024": {
            "run_id": run["id"],
            "status": "done",
            "error": None,
            "done": 8,
            "total": 8,
            "skipped": 0,
        },
        "p1-ru-003": None,
    }
    assert [(d["id"], d["status"]) for d in run["dialogs"]] == [("call-024", "done")]


def test_big_forced_run_without_a_list_asks_for_confirmation(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    store.add_dialogs([d for d in prototype_dialogs() if d.id not in ("call-024", "p1-ru-003")], {})
    with TestClient(
        create_app(settings, source=FakeSource(), evaluator=FakeEvaluator(), conn=conn)
    ) as client:
        refused = client.post("/api/runs", json={"force": True, "criteria": ["01"]})
        assert (refused.status_code, refused.json()) == (
            422,
            {"detail": "Подтвердите перезапуск 10 диалогов"},
        )
        assert client.get("/api/runs").json() == []
        assert _run(client, force=True, confirm=True, criteria=["01"])["total"] == 10


def test_compare_run_answers_in_the_shadow_then_adopt_makes_them_current(api: TestClient) -> None:
    first = _run(api, dialogs=["call-024"])
    other = {
        **PROTO,
        "call-024": {**PROTO["call-024"], "04": PROTO["call-024"]["04"].model_copy(update={"a": 0})},
    }
    api.app.state.runner.use(FakeEvaluator(res=other))  # type: ignore[attr-defined]
    shadow = _run(api, dialogs=["call-024"], apply="compare")
    assert (shadow["total"], shadow["status"]) == (8, "done")

    before = {d["id"]: d for d in api.get("/api/state").json()["dialogs"]}["call-024"]["res"]["04"]["a"]
    rows = api.get("/api/dialogs/call-024/history").json()["04"]
    diffs = api.get(f"/api/runs/compare?a={first['id']}&b={shadow['id']}").json()["diffs"]
    adopted = api.post(f"/api/runs/{shadow['id']}/adopt", json={"criteria": ["04"]})
    after = {d["id"]: d for d in api.get("/api/state").json()["dialogs"]}["call-024"]["res"]["04"]["a"]

    assert before == PROTO["call-024"]["04"].a
    assert [(r["shadow"], r["current"], r["a"]) for r in rows][:2] == [
        (True, False, 0),
        (False, True, before),
    ]
    assert diffs == [{"dialog": "call-024", "cid": "04", "a": before, "b": 0}]
    assert (adopted.status_code, adopted.json()) == (200, {"adopted": 1, "skipped": 0})
    assert after == 0
    replace = api.post(f"/api/runs/{first['id']}/adopt")
    assert replace.status_code == 409 and "сразу" in replace.json()["detail"]


def test_re_check_with_another_model_records_its_settings(api: TestClient) -> None:
    run = _run(api, dialogs=["p1-ru-003"], criteria=["01"], override={"evaluator": "jev"})
    listed = next(r for r in api.get("/api/runs").json() if r["id"] == run["id"])
    assert (listed["model"], listed["override"], listed["force"], listed["apply"]) == (
        "jev-latest", {"evaluator": "jev"}, True, "replace",
    )  # fmt: skip
    assert api.get("/api/config").json()["evaluator"] == "llm"  # saved mode untouched


@pytest.mark.parametrize(
    ("override", "detail"),
    [
        ({"llm_provider": "nope"}, "override.llm_provider: нет провайдера nope"),
        ({"verifier": "nope"}, "override.verifier: нет провайдера nope"),
    ],
)
def test_re_check_with_an_unknown_provider_is_422(
    api: TestClient, override: dict[str, Any], detail: str
) -> None:
    response = api.post("/api/runs", json={"dialogs": ["call-024"], "override": override})
    assert (response.status_code, response.json()) == (422, {"detail": detail})
    assert api.get("/api/runs").json() == []


def test_re_check_with_bad_override_fields_is_422(api: TestClient) -> None:
    for override in ({"evaluator": "gpt"}, {"model": "x"}):
        assert api.post("/api/runs", json={"dialogs": ["call-024"], "override": override}).status_code == 422
    assert api.post("/api/runs", json={"dialogs": ["call-024"], "apply": "merge"}).status_code == 422


def test_re_check_with_jev_without_a_key_outside_replay_is_422(
    store: Store, conn: sqlite3.Connection
) -> None:
    settings = Settings(_env_file=None, db_path=":memory:", llm_mode="live", jev_api_key=None)
    with TestClient(
        create_app(settings, source=FakeSource(), evaluator=FakeEvaluator(), conn=conn)
    ) as client:
        response = client.post("/api/runs", json={"dialogs": ["call-024"], "override": {"evaluator": "jev"}})
    assert response.status_code == 422 and response.json()["detail"].startswith("Перепроверка: Нет ключа Jev")
