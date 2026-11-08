"""`GET /api/dialogs/{id}/prosody`: интонация звонка считается один раз и хранится в базе.

Звук — синтетические кадры: подделка `Voice` вместо скачивания и разбора записи.
"""

import threading

import httpx
import numpy as np
import pytest
from fastapi import FastAPI

from cqa.domain.audio_timeline import utterance_s
from cqa.domain.models import Dialog, Line
from cqa.domain.prosody import Tracks
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeSource, prototype_dialogs

CALL, CHAT = "call-024", "p1-ru-003"
PLAYER = "https://org.test/player/call-024"


def speech_of(dialog: Dialog) -> Tracks:
    """Речь 70 дБ, 150 Гц на месте реплик звонка, тишина 30 дБ вокруг."""
    t = np.arange(0, (dialog.dur or 0) + 5, 0.01)
    f0, db = np.zeros_like(t), np.full_like(t, 30.0)
    for ln in dialog.lines or []:
        if isinstance(ln, Line) and ln.s is not None and ln.who in ("client", "operator"):
            m = (t >= ln.s) & (t < ln.s + utterance_s(ln.text))
            f0[m], db[m] = 150.0, 70.0
    return Tracks(pitch_t=t, f0=f0, int_t=t, db=db)


class FakeVoice:
    def __init__(self, tracks: Tracks | None) -> None:
        self._tracks = tracks
        self.links: list[str] = []
        self.threads: list[int] = []

    async def tracks(self, link: str) -> Tracks | None:
        self.links.append(link)
        self.threads.append(threading.get_ident())
        return self._tracks


class NoLinkSource(FakeSource):
    async def audio_link(self, audio_url: str) -> str | None:
        return None


def dialogs() -> dict[str, Dialog]:
    return {d.id: d for d in prototype_dialogs()}


def make_app(voice: FakeVoice, source: FakeSource | None = None) -> FastAPI:
    app = create_app(Settings(_env_file=None, db_path=":memory:"), source=source or FakeSource())
    ds = dialogs()
    pasted = ds[CALL].model_copy(update={"id": "paste-1"})  # звонок из вставленного текста: записи нет
    app.state.store.add_dialogs([ds[CALL], ds[CHAT], pasted], {CALL: PLAYER})
    app.state.voice = voice
    return app


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_prosody_of_a_call_has_lines_speakers_and_summary() -> None:
    voice = FakeVoice(speech_of(dialogs()[CALL]))
    async with client(make_app(voice)) as c:
        response = await c.get(f"/api/dialogs/{CALL}/prosody")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"lines", "speakers", "summary"}
    assert set(body["speakers"]) == {"client", "operator"}
    assert body["lines"]
    assert all(set(x) == {"n", "f0", "range_st", "db", "wps", "pause", "flags"} for x in body["lines"])
    assert body["speakers"]["operator"]["f0"] == 150.0
    assert voice.links == ["https://storage.test/rec.mp3"]


async def test_prosody_is_computed_once_and_kept_in_the_database() -> None:
    voice = FakeVoice(speech_of(dialogs()[CALL]))
    app = make_app(voice)
    async with client(app) as c:
        first = await c.get(f"/api/dialogs/{CALL}/prosody")
        again = await c.get(f"/api/dialogs/{CALL}/prosody")

    assert again.json() == first.json()
    assert len(voice.links) == 1
    assert app.state.store.prosody(CALL) == first.json()


@pytest.mark.parametrize("dialog_id", [CHAT, "nope", "paste-1"])
async def test_prosody_of_a_chat_unknown_id_or_call_without_record_is_404(dialog_id: str) -> None:
    voice = FakeVoice(None)
    async with client(make_app(voice)) as c:
        response = await c.get(f"/api/dialogs/{dialog_id}/prosody")

    assert response.status_code == 404
    assert "detail" in response.json()
    assert voice.links == []


async def test_prosody_without_fresh_link_is_502_and_not_cached() -> None:
    voice = FakeVoice(speech_of(dialogs()[CALL]))
    app = make_app(voice, NoLinkSource())
    async with client(app) as c:
        response = await c.get(f"/api/dialogs/{CALL}/prosody")

    assert response.status_code == 502
    assert PLAYER not in response.json()["detail"]
    assert voice.links == []
    assert app.state.store.prosody(CALL) is None


async def test_prosody_when_record_does_not_download_is_502_and_retried_later() -> None:
    voice = FakeVoice(None)
    async with client(make_app(voice)) as c:
        first = await c.get(f"/api/dialogs/{CALL}/prosody")
        voice._tracks = speech_of(dialogs()[CALL])
        second = await c.get(f"/api/dialogs/{CALL}/prosody")

    assert first.status_code == 502
    assert "storage.test" not in first.json()["detail"]
    assert second.status_code == 200
    assert len(voice.links) == 2


async def test_prosody_runs_on_the_event_loop_thread_where_the_store_lives() -> None:
    voice = FakeVoice(speech_of(dialogs()[CALL]))
    async with client(make_app(voice)) as c:
        await c.get(f"/api/dialogs/{CALL}/prosody")

    assert voice.threads == [threading.get_ident()]


def test_prosody_route_and_voice_are_connected_in_create_app() -> None:
    app = create_app(Settings(_env_file=None, db_path=":memory:"))

    assert "/api/dialogs/{id}/prosody" in app.openapi()["paths"]
    assert hasattr(app.state.voice, "tracks")
