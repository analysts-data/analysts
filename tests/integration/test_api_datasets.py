import sqlite3

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store, connect
from cqa.domain.models import Dialog
from cqa.http.app import create_app
from cqa.services.errors import Invalid, Upstream
from cqa.settings import Settings
from fakes import FakeSource, prototype_dialogs

DIALOGS = {d.id: d for d in prototype_dialogs()}
SET = [DIALOGS["call-024"], DIALOGS["p1-ru-003"], DIALOGS["p1-ru-025"]]
BROKEN = ["syn-1: нет транскрипта", "syn-2: нет транскрипта"]


@pytest.fixture
def dialogs() -> list[Dialog]:
    """Only call-024 is already loaded."""
    return [DIALOGS["call-024"]]


def _client(settings: Settings, conn: sqlite3.Connection, source: FakeSource | None) -> TestClient:
    return TestClient(create_app(settings, source=source, conn=conn))


def test_group_with_an_already_loaded_dialog(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    response = _client(settings, conn, FakeSource(SET, errors=BROKEN)).post(
        "/api/datasets", json={"group_id": "DEV"}
    )
    assert (response.status_code, response.json()) == (200, {"added": 2, "skipped": 3})


def test_upload_with_an_already_loaded_dialog(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    response = _client(settings, conn, FakeSource(SET, errors=BROKEN)).post(
        "/api/datasets/upload", content=b"{}"
    )
    assert (response.status_code, response.json()) == (200, {"added": 2, "skipped": 3})


def test_file_not_in_the_organizers_format_is_422(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    source = FakeSource(raises={"upload": Invalid("В файле нет поля data.records")})
    response = _client(settings, conn, source).post("/api/datasets/upload", content=b"{}")
    assert (response.status_code, response.json()) == (422, {"detail": "В файле нет поля data.records"})


def test_organizers_api_down_is_502(settings: Settings, store: Store, conn: sqlite3.Connection) -> None:
    source = FakeSource(raises={"fetch": Upstream("API организаторов не ответил за 30 с, group_id DEV")})
    response = _client(settings, conn, source).post("/api/datasets", json={"group_id": "DEV"})
    assert response.status_code == 502
    assert response.json() == {"detail": "API организаторов не ответил за 30 с, group_id DEV"}


def test_blank_group_id_and_empty_file_are_422(
    settings: Settings, store: Store, conn: sqlite3.Connection
) -> None:
    client = _client(settings, conn, FakeSource(SET))
    blank = client.post("/api/datasets", json={"group_id": "  "})
    assert (blank.status_code, blank.json()) == (422, {"detail": "Укажите group_id"})
    empty = client.post("/api/datasets/upload", content=b"")
    assert (empty.status_code, empty.json()) == (422, {"detail": "Пустой файл"})
    assert client.post("/api/datasets", json={}).status_code == 422


def test_audio_link_is_in_the_store_but_not_in_the_state(settings: Settings) -> None:
    conn = connect(":memory:")
    source = FakeSource([DIALOGS["call-024"]], audio={"call-024": "https://org.test/player/1?token=x"})
    client = _client(settings, conn, source)
    assert client.post("/api/datasets", json={"group_id": "DEV"}).status_code == 200
    store = Store(conn)
    assert store.audio_url("call-024") == "https://org.test/player/1?token=x"
    assert store.audio_url("p1-ru-003") is None
    assert "org.test" not in client.get("/api/state").text


@pytest.mark.parametrize(
    ("path", "kwargs"),
    [("/api/datasets", {"json": {"group_id": "DEV"}}), ("/api/datasets/upload", {"content": b"{}"})],
)
def test_without_a_source_loading_is_503(
    settings: Settings, conn: sqlite3.Connection, path: str, kwargs: dict
) -> None:
    # create_app builds the org source by default; the 503 branch covers an explicitly missing source
    app = create_app(settings, conn=conn)
    app.state.source = None
    response = TestClient(app).post(path, **kwargs)
    assert (response.status_code, response.json()) == (503, {"detail": "Загрузка наборов не подключена"})
