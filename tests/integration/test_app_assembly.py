"""Assembly of what the tracks already merged into create_app (review-workflow, group 7)."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from cqa import compose
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeSource, prototype_dialogs

SIGNED = "https://org.test/player/1?token=x"


def _default() -> Settings:
    return Settings(_env_file=None, db_path=":memory:")


def test_app_from_default_settings_serves_the_state() -> None:
    response = TestClient(create_app(_default())).get("/api/state")
    assert response.status_code == 200
    assert set(response.json()) == {"checklist", "versions", "dialogs", "appeals", "owners", "mode", "source"}


def test_loaded_call_has_record_redirects_but_no_signed_address_in_the_state(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    call = next(d for d in prototype_dialogs() if d.id == "call-024")
    app = create_app(settings, source=FakeSource([call], audio={"call-024": SIGNED}), conn=conn)
    client = TestClient(app, follow_redirects=False)
    assert client.post("/api/datasets", json={"group_id": "DEV"}).json() == {"added": 1, "skipped": 0}
    player = client.get("/api/dialogs/call-024/player")
    assert (player.status_code, player.headers["location"]) == (302, SIGNED)
    audio = client.get("/api/dialogs/call-024/audio")
    assert (audio.status_code, audio.headers["location"]) == (302, "https://storage.test/rec.mp3")
    assert "org.test" not in client.get("/api/state").text


@pytest.mark.skipif(not hasattr(compose, "build_evaluator"), reason="build_evaluator ещё не в main")
def test_default_app_can_run_evaluations() -> None:
    assert create_app(_default()).state.runner is not None
