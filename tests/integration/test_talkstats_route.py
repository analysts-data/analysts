"""`GET /api/dialogs/{id}/talkstats` и `GET /api/talkstats/norms`: статистика разговора и нормы команды.

Звонок — из разбора интонации (подделка `Voice` или готовый разбор в базе), чат — по меткам времени.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from test_prosody_route import FakeVoice, speech_of

from cqa.domain.talkstats import CALL as CALL_METRICS
from cqa.domain.talkstats import RULE
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeSource, prototype_dialogs

CALL, CHAT, EMPTY_CHAT = "call-024", "p1-ru-003", "p1-ru-009"
TEAM = [f"call-team-{i}" for i in range(5)]


def make_app(voice: FakeVoice) -> FastAPI:
    app = create_app(Settings(_env_file=None, db_path=":memory:"), source=FakeSource())
    ds = {d.id: d for d in prototype_dialogs()}
    team = [ds[CALL].model_copy(update={"id": i}) for i in TEAM]
    pasted = ds[CALL].model_copy(update={"id": "paste-1"})
    dialogs = [ds[CALL], ds[CHAT], ds[EMPTY_CHAT], pasted, *team]
    app.state.store.add_dialogs(dialogs, {d.id: "https://org.test/player" for d in [ds[CALL], *team]})
    app.state.voice = voice
    return app


def seed(app: FastAPI, dialog_id: str, **talk: float) -> None:
    app.state.store.set_prosody(dialog_id, {"lines": [], "speakers": {}, "summary": [], "talk": talk})


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def by_key(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["key"]: m for m in body["metrics"]}


async def test_call_talkstats_come_from_prosody_and_are_kept_with_it() -> None:
    voice = FakeVoice(speech_of(next(d for d in prototype_dialogs() if d.id == CALL)))
    app = make_app(voice)
    async with client(app) as c:
        response = await c.get(f"/api/dialogs/{CALL}/talkstats")
        again = await c.get(f"/api/dialogs/{CALL}/talkstats")

    assert response.status_code == 200
    body = response.json()
    assert body["ch"] == "call"
    assert body["rule"] == RULE
    assert (body["n"], body["note"]) == (1, "недостаточно данных: 1 из 5 диалогов")
    assert [m["key"] for m in body["metrics"]] == [m.key for m in CALL_METRICS]
    assert all(m["out_of_norm"] is None for m in body["metrics"])
    assert 0 < by_key(body)["operator_share"]["value"] < 100
    assert again.json() == body
    assert len(voice.links) == 1
    assert app.state.store.prosody(CALL)["talk"]["operator_share"] == by_key(body)["operator_share"]["value"]


async def test_call_outside_team_fences_is_out_of_norm() -> None:
    voice = FakeVoice(None)
    app = make_app(voice)
    for dialog_id, mono in zip(TEAM, (10.0, 12.0, 14.0, 16.0, 18.0), strict=True):
        seed(app, dialog_id, monologue_s=mono)
    seed(app, CALL, monologue_s=60.0)
    async with client(app) as c:
        body = (await c.get(f"/api/dialogs/{CALL}/talkstats")).json()

    mono = by_key(body)["monologue_s"]
    assert (body["n"], body["note"]) == (6, None)
    assert mono["out_of_norm"] is True
    assert mono["median"] == 15.0
    assert by_key(body)["pause_max_s"]["out_of_norm"] is None
    assert voice.links == []


async def test_prosody_saved_before_talkstats_is_computed_again() -> None:
    voice = FakeVoice(speech_of(next(d for d in prototype_dialogs() if d.id == CALL)))
    app = make_app(voice)
    app.state.store.set_prosody(CALL, {"lines": [], "speakers": {}, "summary": []})
    async with client(app) as c:
        response = await c.get(f"/api/dialogs/{CALL}/talkstats")

    assert response.status_code == 200
    assert len(voice.links) == 1
    assert "talk" in app.state.store.prosody(CALL)


async def test_chat_talkstats_are_reply_times_from_timestamps() -> None:
    async with client(make_app(FakeVoice(None))) as c:
        body = (await c.get(f"/api/dialogs/{CHAT}/talkstats")).json()

    assert body["ch"] == "chat"
    assert [m["key"] for m in body["metrics"]] == ["reply_median_s", "reply_max_s"]
    assert by_key(body)["reply_max_s"]["value"] > 0


@pytest.mark.parametrize("dialog_id", [EMPTY_CHAT, "nope", "paste-1"])
async def test_talkstats_without_data_are_404(dialog_id: str) -> None:
    async with client(make_app(FakeVoice(None))) as c:
        response = await c.get(f"/api/dialogs/{dialog_id}/talkstats")

    assert response.status_code == 404
    assert "detail" in response.json()


async def test_norms_cover_calls_with_prosody_and_chats() -> None:
    app = make_app(FakeVoice(None))
    for dialog_id, share in zip(TEAM, (40.0, 50.0, 55.0, 60.0, 70.0), strict=True):
        seed(app, dialog_id, operator_share=share)
    async with client(app) as c:
        body = (await c.get("/api/talkstats/norms")).json()

    assert body["rule"] == RULE
    assert (body["call"]["n"], body["call"]["note"]) == (5, None)
    share = by_key(body["call"])["operator_share"]
    assert (share["median"], share["q1"], share["q3"], share["n"]) == (55.0, 50.0, 60.0, 5)
    assert body["chat"]["n"] == 1
    assert body["chat"]["note"] == "недостаточно данных: 1 из 5 диалогов"


async def test_norms_have_per_operator_aggregates() -> None:
    app = make_app(FakeVoice(None))
    for dialog_id, share in zip(TEAM, (40.0, 50.0, 55.0, 60.0, 70.0), strict=True):
        seed(app, dialog_id, operator_share=share)
    for dialog_id in TEAM[:2]:
        app.state.store.set_operator(dialog_id, "Оператор А")
    async with client(app) as c:
        body = (await c.get("/api/talkstats/norms")).json()

    mine = body["operators"]["Оператор А"]
    assert mine["call"]["n"] == 2
    assert by_key(mine["call"])["operator_share"]["median"] == 45.0
    assert mine["chat"]["n"] == 0
    assert set(body["operators"]) == {"Оператор А"}
