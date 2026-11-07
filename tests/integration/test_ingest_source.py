"""OrgDialogSource: один GET, атомарный снимок, разбор файла, журнал без адреса."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from cqa.adapters.org_api import OrgApi
from cqa.compose import build_source
from cqa.domain.models import Line
from cqa.services.errors import Invalid, Upstream
from cqa.services.ingest import OrgDialogSource
from cqa.services.ports import DialogSource
from cqa.settings import Settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "org_payload.json"
TEMPLATE = "https://org.test/api/dialogs?group_id=DEV&token=t"
API = "https://org.test/api/dialogs"
NOW = datetime(2026, 11, 7, 15, 30)


def make_source(tmp_path: Path, url: str | None = TEMPLATE) -> OrgDialogSource:
    settings = Settings(_env_file=None, org_api_url=SecretStr(url) if url else None, raw_dir=tmp_path)
    return OrgDialogSource(settings, OrgApi(url, httpx.AsyncClient()), now=lambda: NOW)


def envelope(records: list[dict[str, Any]], total: int | None = None) -> bytes:
    data = {
        "dataset_group_id": "SYN",
        "total_records": len(records) if total is None else total,
        "records": records,
    }
    return json.dumps({"error": None, "isSuccess": True, "data": data}, ensure_ascii=False).encode()


def fixture_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(FIXTURE.read_bytes())["data"]["records"]
    return records


# --- fetch ---


@respx.mock
async def test_fetch_substitutes_group_id_and_writes_snapshot(tmp_path: Path) -> None:
    body = FIXTURE.read_bytes()
    route = respx.get(API).mock(return_value=httpx.Response(200, content=body))
    result = await make_source(tmp_path).fetch("CTRL1")
    assert route.call_count == 1
    assert str(route.calls.last.request.url) == "https://org.test/api/dialogs?group_id=CTRL1&token=t"
    assert (tmp_path / "CTRL1.json").read_bytes() == body
    assert [d.id for d in result.dialogs] == [r["conversation_id"] for r in fixture_records()]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CTRL1.json"]


@respx.mock
async def test_bad_group_id_is_invalid_without_request(tmp_path: Path) -> None:
    route = respx.get(API).mock(return_value=httpx.Response(200, content=FIXTURE.read_bytes()))
    with pytest.raises(Invalid, match="group_id"):
        await make_source(tmp_path).fetch("../etc")
    assert route.call_count == 0
    assert list(tmp_path.iterdir()) == []


@respx.mock
async def test_org_error_is_upstream_and_keeps_old_snapshot(tmp_path: Path) -> None:
    (tmp_path / "CTRL1.json").write_bytes(b"old")
    error = {"error": "group not found", "isSuccess": False, "data": None}
    route = respx.get(API).mock(return_value=httpx.Response(200, json=error))
    with pytest.raises(Upstream, match="group not found"):
        await make_source(tmp_path).fetch("CTRL1")
    assert route.call_count == 1
    assert (tmp_path / "CTRL1.json").read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CTRL1.json"]


@respx.mock
async def test_api_failure_does_not_leak_address(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    route = respx.get(API).mock(return_value=httpx.Response(500))
    with pytest.raises(Upstream) as exc_info:
        await make_source(tmp_path).fetch("CTRL1")
    assert route.call_count == 1
    for text in (str(exc_info.value), caplog.text):
        assert "org.test" not in text
        assert "token=t" not in text
    assert "CTRL1" in str(exc_info.value)


@respx.mock
async def test_missing_url_is_upstream_without_request(tmp_path: Path) -> None:
    with pytest.raises(Upstream, match="CQA_ORG_API_URL не задан"):
        await make_source(tmp_path, url=None).fetch("DEV")
    assert len(respx.calls) == 0


@respx.mock
async def test_fetch_logs_warnings_and_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    broken = {"conversation_id": "syn-broken", "channel": "agent chat", "language": "ru"}
    body = envelope([*fixture_records(), broken], total=9)
    respx.get(API).mock(return_value=httpx.Response(200, content=body))
    with caplog.at_level(logging.WARNING, logger="cqa.ingest"):
        result = await make_source(tmp_path).fetch("CTRL1")
    assert result.skipped == 1
    logged = [r.getMessage() for r in caplog.records if r.name == "cqa.ingest"]
    assert any(m.startswith("syn-broken:") and "transcript" in m for m in logged)
    assert any("syn-chat-en" in m and "Client joined the chat from a mobile app" in m for m in logged)
    assert any("9" in m and "6" in m and "total_records" in m for m in logged)
    assert "org.test" not in caplog.text


# --- upload ---


@respx.mock
async def test_upload_equals_fetch_and_writes_no_snapshot(tmp_path: Path) -> None:
    body = FIXTURE.read_bytes()
    respx.get(API).mock(return_value=httpx.Response(200, content=body))
    fetched = await make_source(tmp_path / "a").fetch("DEV")
    uploaded = make_source(tmp_path / "b").upload(body)
    assert uploaded == fetched
    assert not (tmp_path / "b").exists()


def test_upload_of_non_json_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(Invalid):
        make_source(tmp_path).upload(b"<html>oops</html>")


def test_upload_skips_broken_record_and_logs_it(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    records = fixture_records()[:3]
    del records[1]["transcript"]
    with caplog.at_level(logging.WARNING, logger="cqa.ingest"):
        result = make_source(tmp_path).upload(envelope(records))
    assert [d.id for d in result.dialogs] == ["syn-chat-ru", "syn-chat-en"]
    assert result.skipped == 1
    assert result.errors[0] in caplog.text


def test_upload_returns_call_audio_links_only(tmp_path: Path) -> None:
    result = make_source(tmp_path).upload(FIXTURE.read_bytes())
    assert sorted(result.audio) == ["syn-call-hold", "syn-call-pause"]
    assert list(tmp_path.iterdir()) == []


# --- сдвиги и сборка ---


def test_audio_shift_comes_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_AUDIO_SHIFT_S", "1.0")
    settings = Settings(_env_file=None, raw_dir=tmp_path)
    source: DialogSource = build_source(settings)
    transcript = [
        {
            "timestamp": "2026-11-01T10:00:00+05:00",
            "speaker": "system",
            "text": "Запись и транскрибирование запущены",
        },
        {
            "timestamp": "2026-11-01T10:00:10+05:00",
            "speaker": "operator",
            "text": "Добрый день, чем могу помочь?",
        },
    ]
    record = {
        "conversation_id": "syn-shift",
        "channel": "voice call",
        "language": "ru",
        "transcript": transcript,
    }
    result = source.upload(envelope([record]))
    lines = [x for x in result.dialogs[0].lines or [] if isinstance(x, Line)]
    assert lines[1].s == 9.0


@respx.mock
def test_build_source_makes_no_requests(tmp_path: Path) -> None:
    build_source(Settings(_env_file=None, org_api_url=SecretStr(TEMPLATE), raw_dir=tmp_path))
    assert len(respx.calls) == 0


# --- запись звонка ---


@respx.mock
async def test_audio_link_asks_the_player_each_time(tmp_path: Path) -> None:
    player = respx.get("https://org.test/player/syn-call-hold").mock(
        return_value=httpx.Response(200, text='<audio><source src="/media/rec.mp3?token=x"></audio>')
    )
    source = make_source(tmp_path)

    first = await source.audio_link("https://org.test/player/syn-call-hold")
    second = await source.audio_link("https://org.test/player/syn-call-hold")

    assert first == second == "https://org.test/media/rec.mp3?token=x"
    assert player.call_count == 2
