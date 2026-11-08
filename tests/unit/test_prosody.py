"""Интонация по кадрам записи: признаки реплик, обычная манера говорящего, отклонения, сводка.

Кадры синтетические: тишина 30 дБ, речь 70 дБ с заданным тоном. Реплика из `w` слов «слово»
занимает по расшифровке (6w − 1) / 14,5 с: 5 слов — 2 с, 10 слов — 4,07 с.
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from cqa.domain.models import Fold, Line
from cqa.domain.prosody import Tracks, analyse

STEP = 0.01
QUIET, LOUD = 30.0, 70.0
OP_HZ, CL_HZ = 120.0, 200.0
Pitch = float | Callable[[np.ndarray], np.ndarray]


def glide(lo: float, hi: float, a: float, b: float) -> Callable[[np.ndarray], np.ndarray]:
    """Тон скользит от lo до hi за реплику [a, b): живая речь, размах 12·log2(hi/lo) полутонов."""
    return lambda t: lo * (hi / lo) ** ((t - a) / (b - a))


def tracks(speech: list[tuple[float, float, Pitch, float]]) -> Tracks:
    t = np.arange(0, max(b for _, b, _, _ in speech) + 2, STEP)
    f0, db = np.zeros_like(t), np.full_like(t, QUIET)
    for a, b, hz, level in speech:
        m = (t >= a) & (t < b)
        f0[m] = hz(t[m]) if callable(hz) else hz
        db[m] = level
    return Tracks(pitch_t=t, f0=f0, int_t=t, db=db)


def line(n: int, who: str, s: float, words: int = 5, seg: str = "conv") -> Line:
    return Line.model_validate(
        {"n": n, "t": s, "who": who, "text": " ".join(["слово"] * words), "s": s, "seg": seg}
    )


def end(ln: Line) -> float:
    assert ln.s is not None
    return ln.s + len(ln.text) / 14.5


def talk(
    lines: list[Line], shift: dict[int, tuple[float, float]] | None = None, flat: frozenset[int] = frozenset()
) -> list[tuple[float, float, Pitch, float]]:
    """Речь ровно на месте реплик: скольжение ±3 полутона вокруг голоса роли, 70 дБ.

    `shift[n] = (полутоны, дБ)` сдвигает реплику n от голоса роли, `flat` — ровный тон без скольжения.
    """
    out: list[tuple[float, float, Pitch, float]] = []
    for ln in lines:
        assert ln.s is not None
        st, db = (shift or {}).get(ln.n, (0.0, 0.0))
        hz = (OP_HZ if ln.who == "operator" else CL_HZ) * 2 ** (st / 12)
        a, b = ln.s, end(ln)
        out.append((a, b, hz if ln.n in flat else glide(hz / 1.19, hz * 1.19, a, b), LOUD + db))
    return out


def dialogue(
    n: int = 8,
    *,
    words: dict[int, int] | None = None,
    gaps: dict[int, float] | None = None,
    seg: dict[int, str] | None = None,
) -> list[Line]:
    """Оператор (нечётные) и клиент (чётные) по очереди, по 5 слов (2 с), паузы 1 с + `gaps[n]`."""
    out: list[Line] = []
    s = 1.0
    for i in range(1, n + 1):
        s += (gaps or {}).get(i, 0.0)
        who = "operator" if i % 2 else "client"
        ln = line(i, who, s, (words or {}).get(i, 5), (seg or {}).get(i, "conv"))
        out.append(ln)
        s = end(ln) + 1.0
    return out


def by_n(result: dict[str, Any], n: int) -> dict[str, Any]:
    return next(x for x in result["lines"] if x["n"] == n)


def test_line_features_come_from_speech_inside_the_line() -> None:
    lines = dialogue(4)
    result = analyse(lines, tracks(talk(lines, {2: (0.0, -6.0)}, flat=frozenset({2}))))

    two = by_n(result, 2)
    assert two["f0"] == CL_HZ
    assert two["db"] == LOUD - 6
    assert two["range_st"] == 0.0
    assert two["wps"] == pytest.approx(2.5, abs=0.1)
    assert two["pause"] == pytest.approx(1.0, abs=0.05)
    assert by_n(result, 1)["range_st"] == pytest.approx(4.8, abs=0.3)  # p10–p90 скольжения на 6 полутонов
    assert [x["n"] for x in result["lines"]] == [1, 2, 3, 4]


def test_speakers_baseline_is_the_median_of_their_lines() -> None:
    lines = dialogue(8)
    result = analyse(lines, tracks(talk(lines)))

    assert result["speakers"]["operator"]["f0"] == pytest.approx(OP_HZ, rel=0.03)
    assert result["speakers"]["client"]["f0"] == pytest.approx(CL_HZ, rel=0.03)
    assert result["speakers"]["client"]["db"] == LOUD
    assert result["speakers"]["client"]["lines"] == 4
    assert all(x["flags"] == [] for x in result["lines"])
    assert result["summary"] == []


def test_raised_tone_is_measured_against_the_speakers_own_voice() -> None:
    lines = dialogue(8)
    result = analyse(lines, tracks(talk(lines, {4: (4.0, 0.0)})))

    assert by_n(result, 4)["flags"] == ["raised"]
    assert by_n(result, 2)["flags"] == []  # клиент выше оператора, но это его обычный голос
    assert result["summary"] == ["Клиент повысил тон в реплике 4"]


def test_louder_line_is_raised_tone() -> None:
    lines = dialogue(8)
    result = analyse(lines, tracks(talk(lines, {3: (0.0, 7.0)})))

    assert by_n(result, 3)["flags"] == ["raised"]
    assert result["summary"] == ["Оператор повысил тон в реплике 3"]


def test_consecutive_lines_of_a_speaker_are_one_range_in_the_summary() -> None:
    lines = dialogue(14)
    result = analyse(lines, tracks(talk(lines, {6: (5.0, 0.0), 8: (5.0, 0.0), 12: (5.0, 0.0)})))

    assert result["summary"] == ["Клиент повысил тон в репликах 6–8, 12"]


def test_flat_tone_on_a_line_of_four_seconds_is_monotone() -> None:
    lines = dialogue(8, words={3: 10, 5: 10})
    result = analyse(lines, tracks(talk(lines, flat=frozenset({3}))))

    assert by_n(result, 3)["flags"] == ["monotone"]
    assert by_n(result, 5)["flags"] == []
    assert result["summary"] == ["Оператор говорит монотонно в реплике 3"]


def test_short_flat_line_is_not_monotone() -> None:
    lines = dialogue(8)
    result = analyse(lines, tracks(talk(lines, flat=frozenset({3}))))

    assert by_n(result, 3)["flags"] == []


def test_fast_line_is_measured_against_the_speakers_own_pace() -> None:
    lines = dialogue(8, words={5: 10})  # 10 слов, а речь — только 2 с в конце реплики
    five = end(lines[4])
    speech = [x for x in talk(lines) if x[0] != lines[4].s] + [(five - 2.0, five, OP_HZ, LOUD)]
    result = analyse(lines, tracks(speech))

    assert by_n(result, 5)["wps"] == pytest.approx(5.0, abs=0.2)
    assert by_n(result, 5)["flags"] == ["fast"]
    assert result["summary"] == ["Оператор говорит быстро в реплике 5"]


def test_long_silence_before_operator_reply_is_a_long_pause() -> None:
    lines = dialogue(8, gaps={5: 8.0})
    result = analyse(lines, tracks(talk(lines)))

    assert by_n(result, 5)["flags"] == ["long_pause"]
    assert by_n(result, 5)["pause"] == pytest.approx(9.0, abs=0.05)
    assert result["summary"] == ["Пауза 9 с перед ответом оператора (реплика 5)"]


def test_pause_around_a_hold_is_not_flagged() -> None:
    lines = dialogue(8, gaps={5: 8.0}, seg={5: "internal"})
    s5 = lines[4].s
    fold = Fold.model_validate({"fold": True, "from": 5, "to": 5, "t0": s5, "t1": s5, "label": "Удержание"})
    result = analyse([*lines[:4], fold, *lines[4:]], tracks(talk(lines)))

    assert all(x["flags"] == [] for x in result["lines"])
    assert result["summary"] == []


def test_silence_before_a_client_line_is_not_a_long_pause() -> None:
    lines = dialogue(8, gaps={6: 8.0})
    result = analyse(lines, tracks(talk(lines)))

    assert by_n(result, 6)["pause"] == pytest.approx(9.0, abs=0.05)
    assert by_n(result, 6)["flags"] == []


def test_line_starting_before_the_previous_one_ends_is_an_overlap() -> None:
    lines = dialogue(8, gaps={4: -2.5})  # клиент начал за 1,5 с до конца реплики оператора
    result = analyse(lines, tracks(talk(lines)))

    assert by_n(result, 4)["flags"] == ["overlap"]
    assert by_n(result, 4)["pause"] == 0.0
    assert result["summary"] == ["Клиент перебил оператора в реплике 4"]


def test_speaker_with_few_lines_gets_no_relative_flags() -> None:
    lines = dialogue(4)
    result = analyse(lines, tracks(talk(lines, {4: (6.0, 10.0)})))

    assert by_n(result, 4)["flags"] == []
    assert result["speakers"]["client"]["lines"] == 2


def test_silent_line_has_no_pitch_and_no_loudness() -> None:
    lines = dialogue(4)
    result = analyse(lines, tracks([x for x in talk(lines) if x[0] != lines[1].s]))

    two = by_n(result, 2)
    assert (two["f0"], two["range_st"], two["db"]) == (None, None, None)


def test_system_lines_and_lines_without_start_are_skipped() -> None:
    lines = dialogue(4)
    sys = Line.model_validate({"n": 9, "t": 0, "who": "system", "text": "Звонок принят", "s": 0.0})
    paused = Line.model_validate({"n": 10, "t": 3, "who": "client", "text": "Да", "s": None, "seg": "conv"})
    result = analyse([sys, *lines, paused], tracks(talk(lines)))

    assert [x["n"] for x in result["lines"]] == [1, 2, 3, 4]
