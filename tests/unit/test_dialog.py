import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cqa.domain.ingest import OrgRecord, build_dialog, ingest_records
from cqa.domain.models import Dialog, Fold, Line

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "org_payload.json"
NOW = datetime(2026, 11, 7, 15, 30, tzinfo=UTC)
SHIFTS = {"shift_s": 0.3, "shift_paused_s": 4.5}
TEXT_29 = "Добрый день, чем могу помочь?"


def raw(cid: str) -> dict[str, Any]:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["records"]
    return next(r for r in records if r["conversation_id"] == cid)


def build(record: dict[str, Any]) -> tuple[Dialog, list[str]]:
    return build_dialog(OrgRecord.model_validate(record), now=NOW, **SHIFTS)


def lines(dialog: Dialog) -> list[Line]:
    return [x for x in dialog.lines or [] if isinstance(x, Line)]


def line(dialog: Dialog, n: int) -> Line:
    return next(x for x in lines(dialog) if x.n == n)


def call(turns: list[tuple[str, str, str]]) -> dict[str, Any]:
    transcript = [{"timestamp": ts, "speaker": who, "text": text} for ts, who, text in turns]
    return {"conversation_id": "syn-x", "channel": "voice call", "language": "ru", "transcript": transcript}


def iso(seconds: float) -> str:
    return f"2026-11-01T10:00:{seconds:010.7f}+05:00"


# --- чат ---


def test_chat_is_normalized_to_contract() -> None:
    source = raw("syn-chat-ru")
    dialog, _ = build(source)
    assert (dialog.id, dialog.ch, dialog.lang, dialog.title) == (
        "syn-chat-ru",
        "chat",
        "RU",
        "Чат syn-chat-ru",
    )
    assert dialog.dur is None
    assert dialog.at == "07.11 15:30"
    assert all(isinstance(x, Line) for x in dialog.lines or [])
    turns = source["transcript"]
    assert [x.n for x in lines(dialog)] == list(range(1, len(turns) + 1))
    for x, turn in zip(lines(dialog), turns, strict=True):
        assert x.t == x.ts == turn["timestamp"]
        assert x.who == turn["speaker"]
        assert x.text == turn["text"]
        assert x.s is None
    assert line(dialog, 4).text == "Здравствуйте, меня зовут [Имя скрыто]. Проверю ваш заказ, минуту."


def test_unknown_speaker_becomes_system_with_warning() -> None:
    source = raw("syn-chat-ru")
    source["transcript"][2]["speaker"] = "agent"
    dialog, warnings = build(source)
    assert line(dialog, 3).who == "system"
    assert any("3" in w and "agent" in w for w in warnings)


def test_unparsed_chat_timestamp_is_kept_with_warning() -> None:
    source = raw("syn-chat-ru")
    source["transcript"][4]["timestamp"] = "??"
    dialog, warnings = build(source)
    assert line(dialog, 5).t == line(dialog, 5).ts == "??"
    assert any("5" in w and "??" in w for w in warnings)


def test_unknown_event_stays_a_line_with_warning() -> None:
    source = raw("syn-chat-ru")
    source["transcript"].insert(
        5, {"timestamp": "02:40", "speaker": "system", "text": "Клиент оценил разговор на 5"}
    )
    dialog, warnings = build(source)
    assert line(dialog, 6).seg == "conv"
    assert any("Клиент оценил разговор на 5" in w for w in warnings)


# --- звонок ---


def test_call_with_seven_fraction_digits() -> None:
    turns = [
        (iso(0), "bot", "Здравствуйте! Вы позвонили в банк."),
        (iso(3), "client", "Алло."),
        (iso(6), "bot", "Соединяю с оператором."),
        (iso(9), "client", "Жду."),
        ("2026-11-01T10:00:14.1234567+05:00", "bot", "Оператор подключается."),
        (iso(15), "system", "Запись и транскрибирование запущены"),
        (iso(25), "operator", TEXT_29),
        (iso(30.5), "client", "Спасибо, до свидания."),
    ]
    dialog, _ = build(call(turns))
    fifth = line(dialog, 5)
    assert fifth.s is None
    assert fifth.t == 14.1
    assert fifth.ts == "2026-11-01T10:00:14.1234567+05:00"
    assert dialog.ch == "call"
    assert dialog.at == "01.11 10:00"
    assert dialog.title is not None and dialog.title.startswith("Звонок")
    assert dialog.dur == 30.5


def test_unparsed_call_timestamp_takes_previous_time() -> None:
    turns = [
        (iso(0), "bot", "Здравствуйте!"),
        (iso(4), "client", "Алло."),
        ("??", "client", "Слышно?"),
        (iso(8), "system", "Запись и транскрибирование запущены"),
        (iso(18), "operator", TEXT_29),
    ]
    dialog, warnings = build(call(turns))
    assert line(dialog, 2).t == 4.0
    assert (line(dialog, 3).t, line(dialog, 3).ts) == (4.0, "??")
    assert any("3" in w and "??" in w for w in warnings)


def test_hold_call_folds_internal_and_after_parts() -> None:
    dialog, _ = build(raw("syn-call-hold"))
    items = dialog.lines or []
    assert len(items) == 18
    folds = [(i, x) for i, x in enumerate(items) if isinstance(x, Fold)]
    assert len(folds) == 2
    (i1, hold), (i2, tail) = folds
    assert isinstance(items[i1 + 1], Line) and items[i1 + 1].n == 7
    assert (hold.from_, hold.to, hold.label) == (7, 12, "Удержание и разговор с коллегой")
    assert (hold.t0, hold.t1) == (line(dialog, 7).t, line(dialog, 12).t)
    assert isinstance(items[i2 + 1], Line) and items[i2 + 1].n == 16
    assert (tail.from_, tail.to, tail.label) == (16, 16, "После конца разговора")
    assert (tail.t0, tail.t1) == (line(dialog, 16).t, line(dialog, 16).t)
    assert [x.seg for x in lines(dialog)] == ["pre"] * 3 + ["conv"] * 3 + ["internal"] * 6 + ["conv"] * 3 + [
        "after"
    ]


def test_recognition_duplicate_is_marked_not_removed() -> None:
    dialog, warnings = build(raw("syn-call-hold"))
    assert (line(dialog, 13).text, line(dialog, 14).text) == ("Минуту, проверю.", "минуту,  проверю")
    assert line(dialog, 14).dup is True
    assert line(dialog, 13).dup is None
    assert "dup" not in line(dialog, 13).model_dump(exclude_unset=True)
    assert any("реплика 14 повторяет 13" in w for w in warnings)


def test_chat_fold_times_are_seconds_of_mmss() -> None:
    source = raw("syn-chat-ru")
    source["transcript"].insert(6, {"timestamp": "03:01", "speaker": "system", "text": "Клиент покинул чат"})
    dialog, _ = build(source)
    tail = next(x for x in dialog.lines or [] if isinstance(x, Fold))
    assert (tail.from_, tail.to, tail.t0, tail.t1) == (8, 8, 196.0, 196.0)


# --- пакет ---


def records() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["records"]


def ingest(batch: list[dict[str, Any]]) -> tuple[Any, list[str]]:
    return ingest_records(batch, group_id="SYN", now=NOW, **SHIFTS)


def test_fixture_gives_one_dialog_per_record_and_audio_only_for_calls() -> None:
    result, _ = ingest(records())
    assert [d.id for d in result.dialogs] == [r["conversation_id"] for r in records()]
    assert result.audio == {
        "syn-call-hold": "https://org.test/player/syn-call-hold",
        "syn-call-pause": "https://org.test/player/syn-call-pause",
    }
    assert (result.skipped, result.errors) == (0, [])


def test_repeated_id_keeps_last_record_with_warning() -> None:
    first, second = raw("syn-chat-ru"), raw("syn-chat-ru")
    second["transcript"] = second["transcript"][:3]
    result, warnings = ingest([first, raw("syn-chat-en"), second])
    assert [d.id for d in result.dialogs] == ["syn-chat-ru", "syn-chat-en"]
    assert len(lines(result.dialogs[0])) == 3
    assert any(w.startswith("syn-chat-ru:") and "повтор" in w for w in warnings)


def test_broken_record_is_skipped_with_its_id() -> None:
    broken = raw("syn-chat-kz")
    del broken["transcript"]
    result, _ = ingest([raw("syn-chat-ru"), broken, raw("syn-chat-en")])
    assert [d.id for d in result.dialogs] == ["syn-chat-ru", "syn-chat-en"]
    assert result.skipped == 1
    assert len(result.errors) == 1 and result.errors[0].startswith("syn-chat-kz:")
    assert "transcript" in result.errors[0]


def test_warnings_name_the_conversation() -> None:
    _, warnings = ingest(records())
    assert any(
        w.startswith("syn-chat-en:") and "Client joined the chat from a mobile app" in w for w in warnings
    )
    assert any(w.startswith("syn-call-hold:") and "реплика 14 повторяет 13" in w for w in warnings)


def test_same_records_and_now_give_equal_results() -> None:
    assert ingest(records()) == ingest(records())


# --- время в записи ---


def test_paused_call_uses_paused_shift_for_every_line() -> None:
    dialog, _ = build(raw("syn-call-pause"))
    assert line(dialog, 2).s == line(dialog, 2).t == 22.5
    assert line(dialog, 4).s is None
    assert line(dialog, 4).t == 40.0
    assert line(dialog, 6).s == line(dialog, 6).t == 47.5


def test_hold_call_lines_before_recording_have_no_start() -> None:
    dialog, _ = build(raw("syn-call-hold"))
    assert line(dialog, 1).s is None and line(dialog, 2).s is None
    assert line(dialog, 4).s is not None
    assert line(dialog, 4).t == line(dialog, 4).s


def test_call_time_matches_player() -> None:
    turns = [
        (iso(0), "bot", "Здравствуйте!"),
        (iso(4), "client", "Алло."),
        (iso(6), "bot", "Соединяю."),
        (iso(8), "system", "Запись и транскрибирование запущены"),
        (iso(18), "operator", TEXT_29),
    ]
    dialog, _ = build(call(turns))
    assert [line(dialog, n).t for n in (1, 2, 3)] == [0.0, 4.0, 6.0]
    assert line(dialog, 5).t == line(dialog, 5).s == 8.3
