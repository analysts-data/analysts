"""Статистика разговора: доли речи, монолог, паузы, перебивания, тишина, темп; нормы команды по Тьюки.

Отрезки речи синтетические: `Span(кто, начало, конец, слов)` вместо разбора записи.
"""

import pytest

from cqa.domain.models import Fold, Line
from cqa.domain.talkstats import CALL, CHAT, Span, call_stats, chat_stats, mark, norms


def op(start: float, end: float, words: int = 5, **kw: bool) -> Span:
    return Span("operator", start, end, words, **kw)


def cl(start: float, end: float, words: int = 5, **kw: bool) -> Span:
    return Span("client", start, end, words, **kw)


def test_call_stats_from_speech_spans() -> None:
    spans = [op(0, 6, 12), cl(7, 9, 4), op(12, 16, 8), op(17, 20, 6), cl(19, 21, 4, interrupt=True)]

    stats = call_stats(spans)

    assert stats["operator_share"] == pytest.approx(100 * 13 / 17, abs=0.1)
    assert stats["monologue_s"] == 8.0  # 12–20: две реплики оператора подряд
    assert (
        stats["pause_median_s"] == stats["pause_max_s"] == 3.0
    )  # ответ клиенту 12 − 9; внутри монолога — нет
    assert stats["interrupt_client"] == 1
    assert stats["interrupt_operator"] == 0
    assert stats["silence_share"] == pytest.approx(100 * 5 / 21, abs=0.1)  # 6–7, 9–12, 16–17 из 0–21
    assert stats["wps_operator"] == pytest.approx(26 / 13, abs=0.05)
    assert stats["wps_client"] == 2.0


def test_pause_stats_are_median_and_max_over_operator_replies() -> None:
    spans = [cl(0, 2), op(3, 5), cl(6, 8), op(12, 14), cl(15, 17), op(19, 21)]

    stats = call_stats(spans)

    assert stats["pause_median_s"] == 2.0  # 1, 4, 2
    assert stats["pause_max_s"] == 4.0


def test_hold_splits_the_call_and_its_silence_is_not_counted() -> None:
    spans = [op(0, 4), cl(5, 7), op(8, 10, scored=False), op(300, 304), cl(305, 307)]

    stats = call_stats(spans)

    assert stats["silence_share"] == pytest.approx(100 * 2 / 14, abs=0.1)  # 0–7 и 300–307
    assert stats["monologue_s"] == 4.0
    assert stats["pause_max_s"] is None  # оператор после удержания отвечает не на реплику клиента


def test_call_without_operator_replies_has_no_pause_stats() -> None:
    stats = call_stats([op(0, 3), op(4, 6)])

    assert stats["pause_median_s"] is None
    assert stats["operator_share"] == 100.0
    assert stats["wps_client"] is None


def test_call_without_speech_has_no_stats() -> None:
    assert call_stats([]) == {m.key: None for m in CALL}


def line(n: int, who: str, t: str, seg: str | None = "conv") -> Line:
    return Line.model_validate({"n": n, "t": t, "ts": t, "who": who, "text": "текст", "seg": seg})


def test_chat_reply_time_counts_from_the_first_unanswered_client_message() -> None:
    lines: list[Line | Fold] = [
        line(1, "client", "00:03", "pre"),
        line(2, "system", "00:04", "pre"),
        line(3, "client", "00:10"),
        line(4, "client", "00:20"),
        line(5, "operator", "00:40"),  # 30 с от сообщения 3
        line(6, "operator", "00:50"),
        line(7, "client", "01:00"),
        line(8, "operator", "01:10"),  # 10 с
    ]

    stats = chat_stats(lines)

    assert stats == {"reply_median_s": 20.0, "reply_max_s": 30.0}


def test_chat_without_parsable_times_or_replies_has_no_stats() -> None:
    assert chat_stats([line(1, "client", "вчера"), line(2, "operator", "позже")]) is None
    assert chat_stats([line(1, "client", "00:01"), line(2, "client", "00:05")]) is None


def test_norms_are_median_and_tukey_fences_over_dialogues() -> None:
    rows = [{"monologue_s": v} for v in (10.0, 12.0, 14.0, 16.0, 18.0, None)]

    section = norms(rows, CALL)
    mono = next(m for m in section["metrics"] if m["key"] == "monologue_s")

    assert section["n"] == 6
    assert section["note"] is None
    assert mono == {
        "key": "monologue_s",
        "label": "Самый долгий монолог оператора",
        "unit": "с",
        "n": 5,
        "median": 14.0,
        "q1": 12.0,
        "q3": 16.0,
        "iqr": 4.0,
        "lo": 6.0,
        "hi": 22.0,
    }


def test_fewer_than_five_dialogues_give_no_fences() -> None:
    section = norms([{"reply_max_s": 5.0}, {"reply_max_s": 7.0}], CHAT)
    reply = next(m for m in section["metrics"] if m["key"] == "reply_max_s")

    assert section["note"] == "недостаточно данных: 2 из 5 диалогов"
    assert reply["median"] == 6.0
    assert reply["lo"] is None and reply["hi"] is None


def test_value_outside_the_fences_is_out_of_norm() -> None:
    rows = [{"monologue_s": v} for v in (10.0, 12.0, 14.0, 16.0, 18.0)]
    section = norms(rows, CALL)

    marked = {m["key"]: m for m in mark({"monologue_s": 40.0, "pause_max_s": None}, section)}

    assert marked["monologue_s"]["out_of_norm"] is True
    assert marked["monologue_s"]["value"] == 40.0
    assert marked["monologue_s"]["median"] == 14.0
    assert marked["pause_max_s"]["out_of_norm"] is None
    assert mark({"monologue_s": 15.0}, section)[1]["out_of_norm"] is False
    assert [m["key"] for m in mark({}, section)] == [m.key for m in CALL]


def test_without_enough_dialogues_nothing_is_out_of_norm() -> None:
    section = norms([{"monologue_s": 1.0}], CALL)

    assert all(m["out_of_norm"] is None for m in mark({"monologue_s": 100.0}, section))
