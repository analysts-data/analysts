import sqlite3

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings


def test_state_answers_with_seven_keys(client: TestClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    assert set(response.json()) == {
        "checklist",
        "versions",
        "dialogs",
        "appeals",
        "owners",
        "mode",
        "source",
        "sources",
    }


def test_empty_base_is_seeded_once(settings: Settings, conn: sqlite3.Connection) -> None:
    create_app(settings, conn=conn)
    create_app(settings, conn=conn)
    assert Store(conn).list_versions() == [{"v": 3, "note": "начальная версия"}]
