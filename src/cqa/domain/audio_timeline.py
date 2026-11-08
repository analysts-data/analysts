"""Начало реплики звонка в аудиофайле по метке её конца."""

from collections.abc import Sequence
from math import inf
from typing import Final

from cqa.domain.events import EventKind

CHARS_PER_S: Final = 14.5
MIN_UTTERANCE_S: Final = 0.6


def utterance_s(text: str) -> float:
    """Оценка длительности реплики по тексту: `s` + она = метка конца реплики в записи."""
    return max(MIN_UTTERANCE_S, len(text) / CHARS_PER_S)


def audio_starts(
    ends: Sequence[float],
    texts: Sequence[str],
    who: Sequence[str],
    kinds: Sequence[EventKind | None],
    *,
    shift_s: float,
    shift_paused_s: float,
) -> list[float | None]:
    """`s = max(0, A(w) − d)`, `A(w) = (w − rec_start) − закрытые паузы до w + shift`, до 0,1.

    `None` — реплика раньше старта записи или внутри паузы. Незакрытая пауза длится до конца.
    """
    if not ends:
        return []
    rec_start = next((w for w, k in zip(ends, kinds, strict=True) if k == "rec_start"), ends[0])
    pauses: list[tuple[float, float]] = []
    for w, k in zip(ends, kinds, strict=True):
        is_open = bool(pauses) and pauses[-1][1] == inf
        if k == "rec_pause" and not is_open:
            pauses.append((w, inf))
        elif k == "rec_resume" and is_open:
            pauses[-1] = (pauses[-1][0], w)
    shift = shift_paused_s if pauses else shift_s

    starts: list[float | None] = []
    for w, text, role in zip(ends, texts, who, strict=True):
        if w < rec_start or any(p < w < r for p, r in pauses):
            starts.append(None)
            continue
        a = w - rec_start - sum(r - p for p, r in pauses if r <= w) + shift
        d = 0.0 if role == "system" else utterance_s(text)
        starts.append(round(max(0.0, a - d), 1))
    return starts
