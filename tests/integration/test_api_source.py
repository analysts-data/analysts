"""PUT /api/source: ссылка API организаторов из интерфейса, автосинхронизация, ссылка не уходит в ответы."""

import sqlite3
import time

from fastapi.testclient import TestClient

from cqa.adapters.store import Store, connect
from cqa.http.app import create_app
from cqa.services.errors import Upstream
from cqa.settings import Settings
from fakes import FakeSource, prototype_dialogs

DIALOGS = {d.id: d for d in prototype_dialogs()}
URL = "https://org.test/api/dialogs?group_id=DEV&token=t"


def _client(settings: Settings, conn: sqlite3.Connection, source: FakeSource) -> TestClient:
    return TestClient(create_app(settings, source=source, conn=conn))


def test_put_source_loads_the_group_and_saves_the_link(settings: Settings) -> None:
    conn = connect(":memory:")
    source = FakeSource([DIALOGS["call-024"]])
    response = _client(settings, conn, source).put("/api/source", json={"url": URL, "group_id": "DEV"})
    assert (response.status_code, response.json()) == (200, {"added": 1, "skipped": 0})
    assert source.fetched == [("DEV", URL)]
    assert Store(conn).org_source() == (URL, "DEV")


def test_state_shows_the_sync_status_but_not_the_link(settings: Settings) -> None:
    client = _client(settings, connect(":memory:"), FakeSource([DIALOGS["call-024"]]))
    assert client.get("/api/state").json()["source"] is None
    client.put("/api/source", json={"url": URL, "group_id": "DEV"})
    state = client.get("/api/state")
    assert state.json()["source"]["group_id"] == "DEV"
    assert "org.test" not in state.text


def test_put_source_with_a_plain_http_link_is_422(settings: Settings) -> None:
    client = _client(settings, connect(":memory:"), FakeSource())
    response = client.put("/api/source", json={"url": "http://org.test/api", "group_id": "DEV"})
    assert response.status_code == 422
    assert "https://" in response.json()["detail"]


def test_put_source_when_the_organizers_api_is_down_is_502(settings: Settings) -> None:
    source = FakeSource(raises={"fetch": Upstream("набор DEV: API организаторов недоступен")})
    response = _client(settings, connect(":memory:"), source).put(
        "/api/source", json={"url": URL, "group_id": "DEV"}
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "набор DEV: API организаторов недоступен"}


def test_running_app_syncs_the_saved_group(settings: Settings) -> None:
    conn = connect(":memory:")
    Store(conn).set_org_source(URL, "DEV")
    source = FakeSource([DIALOGS["call-024"]])
    with _client(settings, conn, source) as client:
        deadline = time.monotonic() + 2
        while not source.fetched and time.monotonic() < deadline:
            time.sleep(0.01)
        assert source.fetched == [("DEV", URL)]
        assert [d["id"] for d in client.get("/api/state").json()["dialogs"]] == ["call-024"]
