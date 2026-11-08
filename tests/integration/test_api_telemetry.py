"""POST /api/telemetry и GET /api/usage: проверка, белый список, размеры, без текста, выключатель."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.services.telemetry import TokenBucket
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource

NOW = datetime.now(UTC).isoformat()


def batch(*events: str, **props: object) -> list[dict[str, object]]:
    return [{"event": e, "at": NOW, "page": "queue", "props": props} for e in events]


def rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT actor, role, event, page, props FROM telemetry ORDER BY id").fetchall()


def test_batch_is_stored_with_role_as_actor_and_returns_204(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.post("/api/telemetry?role=operator", json=batch("page_view", "action"))

    assert response.status_code == 204
    assert [(r["actor"], r["role"], r["event"], r["page"]) for r in rows(conn)] == [
        ("operator", "operator", "page_view", "queue"),
        ("operator", "operator", "action", "queue"),
    ]


def test_user_header_is_the_actor(client: TestClient, conn: sqlite3.Connection) -> None:
    client.post("/api/telemetry?role=qa", json=batch("page_view"), headers={"X-CQA-User": "ivanova"})

    assert (rows(conn)[0]["actor"], rows(conn)[0]["role"]) == ("ivanova", "qa")


def test_beacon_body_as_text_plain_is_accepted(client: TestClient, conn: sqlite3.Connection) -> None:
    body = json.dumps(batch("help_open"))

    response = client.post(
        "/api/telemetry", content=body, headers={"Content-Type": "text/plain;charset=UTF-8"}
    )

    assert response.status_code == 204
    assert rows(conn)[0]["actor"] == "—"


def test_search_text_and_dialogue_are_never_stored(client: TestClient, conn: sqlite3.Connection) -> None:
    client.post(
        "/api/telemetry", json=batch("search", q="Иванов вернуть деньги", text="Клиент: где мои деньги")
    )

    stored = rows(conn)[0]["props"]
    assert json.loads(stored) == {"len": 21}
    assert "Иванов" not in stored and "деньги" not in stored


def test_unknown_event_rejects_the_batch(client: TestClient, conn: sqlite3.Connection) -> None:
    assert client.post("/api/telemetry", json=batch("page_view", "keylogger")).status_code == 422
    assert rows(conn) == []


def test_size_limits_are_422(client: TestClient) -> None:
    assert client.post("/api/telemetry", json=batch(*["page_view"] * 201)).status_code == 422
    assert client.post("/api/telemetry", json=batch("action", act="x" * 2100)).status_code == 422
    assert (
        client.post("/api/telemetry", json=[{"event": "page_view", "page": "очередь с пробелом"}]).status_code
        == 422
    )
    assert client.post("/api/telemetry", content=b"not json").status_code == 422


def test_rate_limit_answers_429(client: TestClient) -> None:
    client.app.state.telemetry_limit = TokenBucket(capacity=1, rate=0.0)  # type: ignore[attr-defined]

    assert client.post("/api/telemetry", json=batch("page_view")).status_code == 204
    assert client.post("/api/telemetry", json=batch("page_view")).status_code == 429


def test_off_switch_accepts_and_stores_nothing(store: Store, conn: sqlite3.Connection) -> None:
    app = create_app(
        Settings(_env_file=None, db_path=":memory:", telemetry="off"),
        source=FakeSource([]),
        evaluator=FakeEvaluator(),
        conn=conn,
    )

    assert TestClient(app).post("/api/telemetry", json=batch("page_view")).status_code == 204
    assert rows(conn) == []


def test_retention_drops_old_events_on_startup(store: Store, conn: sqlite3.Connection) -> None:
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    store.add_telemetry(
        [(old, "qa", "qa", "page_view", "queue", "{}"), (NOW, "qa", "qa", "page_view", "queue", "{}")]
    )

    create_app(
        Settings(_env_file=None, db_path=":memory:"),
        source=FakeSource([]),
        evaluator=FakeEvaluator(),
        conn=conn,
    )

    assert len(rows(conn)) == 1


def test_events_are_append_only(store: Store, conn: sqlite3.Connection) -> None:
    store.add_telemetry([(NOW, "qa", "qa", "page_view", "queue", "{}")])

    try:
        conn.execute("UPDATE telemetry SET actor = 'x'")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("UPDATE прошёл")


def test_usage_json_filters_by_role_and_csv_downloads(client: TestClient) -> None:
    client.post("/api/telemetry?role=qa", json=batch("dialog_open", "appeal_submit", id="d1"))
    client.post("/api/telemetry?role=operator", json=batch("page_view"))

    every = client.get("/api/usage").json()
    qa = client.get("/api/usage?role=qa&since=2026-01-01").json()
    csv = client.get("/api/usage?format=csv")

    assert (every["events"], qa["events"], qa["filters"]) == (3, 2, {"since": "2026-01-01", "role": "qa"})
    assert qa["funnels"][0]["converted"] == 1
    assert csv.headers["content-type"] == "text/csv; charset=utf-8"
    assert 'filename="usage.csv"' in csv.headers["content-disposition"]
    assert client.get("/api/usage?format=pdf").status_code == 422
