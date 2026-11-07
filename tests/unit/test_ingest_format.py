"""Формат организаторов: фикстура `tests/fixtures/org_payload.json`, разбор меток и конверта."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cqa.domain.ingest import ts_seconds

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "org_payload.json"

# маркеры подписанных ссылок собираем по частям, чтобы файл теста сам их не содержал
FORBIDDEN_MARKERS = ("si" + "g=", "dyna" + "mics.com", "power" + "platform.com")


def test_ts_seconds_mmss() -> None:
    assert ts_seconds("01:10") == 70


def test_ts_seconds_hmmss() -> None:
    assert ts_seconds("1:02:03") == 3723


def test_ts_seconds_iso_with_seven_fraction_digits() -> None:
    """Дробь обрезается до 6 знаков, пояс учитывается, секунды POSIX."""
    ts = "2026-11-01T10:00:14.1234567+05:00"
    expected = datetime(2026, 11, 1, 5, 0, 14, 123456, tzinfo=UTC).timestamp()
    assert ts_seconds(ts) == expected


def test_ts_seconds_iso_z_equals_explicit_utc() -> None:
    assert ts_seconds("2026-11-01T05:00:00Z") == ts_seconds("2026-11-01T05:00:00+00:00")


def test_ts_seconds_without_timezone_is_utc() -> None:
    assert ts_seconds("2026-11-01T05:00:00") == ts_seconds("2026-11-01T05:00:00+00:00")


@pytest.mark.parametrize("bad", ["??", "", "10:99", "01.10"])
def test_ts_seconds_unparsable_returns_none(bad: str) -> None:
    assert ts_seconds(bad) is None


def test_org_payload_fixture_is_valid_envelope() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert data["error"] is None
    assert data["isSuccess"] is True

    payload = data["data"]
    assert payload["dataset_group_id"] == "SYN"
    assert payload["total_records"] == 5
    records = payload["records"]
    assert len(records) == 5
    assert [r["conversation_id"] for r in records] == [
        "syn-chat-ru",
        "syn-chat-kz",
        "syn-chat-en",
        "syn-call-hold",
        "syn-call-pause",
    ]
    for record in records:
        assert record["transcript"]
        for turn in record["transcript"]:
            assert {"timestamp", "speaker", "text"} <= set(turn)


def test_org_payload_fixture_calls_and_chats() -> None:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["records"]
    calls = [r for r in records if r["channel"] == "voice call"]
    chats = [r for r in records if r["channel"] == "agent chat"]

    assert len(calls) == 2
    assert len(chats) == 3
    assert all(r["audio_url"] == f"https://org.test/player/{r['conversation_id']}" for r in calls)
    assert all(r["audio_url"] is None for r in chats)


def test_org_payload_fixture_hold_call_shape() -> None:
    """`syn-call-hold`: 16 реплик сценария сегментов, ISO с семью знаками дроби."""
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["records"]
    hold = next(r for r in records if r["conversation_id"] == "syn-call-hold")

    turns = hold["transcript"]
    assert len(turns) == 16
    assert all(len(t["timestamp"].split(".")[-1].split("+")[0]) == 7 for t in turns)
    assert turns[2]["text"] == "Запись и транскрибирование запущены"
    assert turns[2]["speaker"] == "system"
    assert turns[12]["text"] == "Минуту, проверю."
    assert turns[13]["text"] == "минуту,  проверю"
    assert turns[13]["speaker"] == turns[12]["speaker"] == "operator"
    assert turns[14]["timestamp"] == turns[15]["timestamp"]


def test_org_payload_fixture_pause_call_texts_are_29_chars() -> None:
    """`syn-call-pause`: реплики по 29 символов, чтобы `s` считались вручную."""
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["records"]
    pause = next(r for r in records if r["conversation_id"] == "syn-call-pause")

    texts = [t["text"] for t in pause["transcript"] if t["speaker"] != "system"]
    assert len(texts) == 3
    assert [len(t) for t in texts] == [29, 29, 29]


def test_org_payload_fixture_has_no_signed_links() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    for marker in FORBIDDEN_MARKERS:
        assert marker not in text

    script = FIXTURE.parents[2] / "scripts" / "secret_scan.sh"
    if os.access(script, os.X_OK):
        result = subprocess.run([str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
