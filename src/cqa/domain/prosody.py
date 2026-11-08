"""Интонация звонка по звуку: признаки реплик, обычная манера говорящего, отклонения и сводка.

Чистый модуль. Кадры F0 и интенсивности готовит адаптер `cqa.adapters.voice`. Запись моно, поэтому
реплика ищется по расшифровке: метка конца `e = s + utterance_s(text)`, речь — громкие кадры
между концом предыдущей реплики и `e`. Так длительность и темп берутся из звука, а не из текста.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import log2
from statistics import median
from typing import Any, Final, Literal

import numpy as np
import numpy.typing as npt

from cqa.domain.audio_timeline import MIN_UTTERANCE_S, utterance_s
from cqa.domain.models import Fold, Line

# ponytail: пороги эвристические, по литературе о просодии и прослушиванию звонков DEV, не обучены;
# калибровать на звонках с разметкой специалистов КК
RAISED_ST: Final = 3.0  # тон выше обычного для говорящего, полутоны
RAISED_DB: Final = 6.0  # громче обычного для говорящего, дБ
MONOTONE_ST: Final = 2.0  # размах тона реплики p10–p90 меньше, полутоны
MONOTONE_MIN_S: Final = 4.0
FAST_RATIO: Final = 1.5  # темп от обычного для говорящего
FAST_MIN_WPS: Final = 3.5  # и не меньше, слов в секунду
LONG_PAUSE_S: Final = 5.0  # тишина перед ответом оператора клиенту
OVERLAP_MIN_S: Final = 1.0  # реплика началась раньше конца чужой
SPEECH_RANGE_DB: Final = 25.0  # речь — кадры не тише 95-го процентиля записи минус столько
GAP_IN_LINE_S: Final = 0.5  # тишина короче — пауза внутри реплики, длиннее — граница с предыдущей
MIN_BASELINE_LINES: Final = 3  # меньше реплик — обычной манеры нет, относительных отклонений тоже
MIN_VOICED: Final = 10  # кадров с тоном для медианы и размаха

Who = Literal["client", "operator"]
Flag = Literal["raised", "monotone", "fast", "long_pause", "overlap"]
Array = npt.NDArray[np.float64]

SCORED = ("conv", None)  # сегменты, где отклонения считаются: удержание и разговор с коллегой — нет
NAME: Final = {"client": "Клиент", "operator": "Оператор"}
OTHER: Final = {"client": "оператора", "operator": "клиента"}
PHRASE: Final = {
    "raised": "{who} повысил тон",
    "monotone": "{who} говорит монотонно",
    "fast": "{who} говорит быстро",
    "overlap": "{who} перебил {other}",
}


@dataclass(frozen=True)
class Tracks:
    """Кадры записи: время, с, и F0, Гц (0 — тона нет); время и интенсивность, дБ."""

    pitch_t: Array
    f0: Array
    int_t: Array
    db: Array


@dataclass
class _Feat:
    line: Line
    who: Who
    start: float  # речь в записи, с
    end: float
    overlap: float  # на столько начало раньше конца предыдущей чужой реплики
    f0: float | None
    range_st: float | None
    db: float | None
    pause: float | None
    flags: list[Flag] = field(default_factory=list)

    @property
    def scored(self) -> bool:
        return self.line.seg in SCORED

    @property
    def dur(self) -> float:
        return self.end - self.start

    @property
    def wps(self) -> float:
        return len(self.line.text.split()) / max(self.dur, MIN_UTTERANCE_S)


def _st(hi: float, lo: float) -> float:
    return 12 * log2(hi / lo)


def _speech(t: Array, loud: npt.NDArray[np.bool_], s: float) -> tuple[float, float] | None:
    """Речь реплики среди громких кадров окна: всё от оценки начала `s` до конца окна и то, что
    примыкает к этому слева короче `GAP_IN_LINE_S`. Хвост предыдущего говорящего за его меткой
    отделён тишиной и в реплику не попадает."""
    times = t[loud]
    if not len(times):
        return None
    inside = np.flatnonzero(times >= s)
    k = int(inside[0]) if len(inside) else len(times) - 1
    gaps = np.flatnonzero(np.diff(times[: k + 1]) > GAP_IN_LINE_S)
    return float(times[gaps[-1] + 1] if len(gaps) else times[0]), float(times[-1])


def _features(lines: Sequence[Line | Fold], tr: Tracks) -> list[_Feat]:
    loud = float(np.percentile(tr.db, 95)) - SPEECH_RANGE_DB if len(tr.db) else 0.0
    out: list[_Feat] = []
    sounding = [x for x in lines if isinstance(x, Line) and x.s is not None and x.who != "system"]
    starts = [x.s or 0.0 for x in sounding]
    prev_end, prev_who = 0.0, ""  # метка конца и роль предыдущей звучащей реплики, бот тоже
    for k, ln in enumerate(sounding):
        s, mark = starts[k], starts[k] + utterance_s(ln.text)
        lo, after_speaker = min(s, prev_end), prev_who in NAME
        overlap = max(0.0, prev_end - s) if after_speaker and prev_who != ln.who else 0.0
        prev_end, prev_who = mark, ln.who
        if ln.who not in NAME:
            continue
        found = _speech(tr.int_t, (tr.int_t >= lo) & (tr.int_t <= mark) & (tr.db >= loud), s)
        start, end = found or (s, mark)
        hi = min(end, starts[k + 1]) if k + 1 < len(starts) else end  # тон и громкость — без хвоста
        own = (tr.int_t >= start) & (tr.int_t <= hi) & (tr.db >= loud)  # под следующей: там звучат оба
        voiced = tr.f0[(tr.pitch_t >= start) & (tr.pitch_t <= hi) & (tr.f0 > 0)]
        f0 = rng = None
        if len(voiced) >= MIN_VOICED:
            p10, p50, p90 = np.percentile(voiced, [10, 50, 90])
            f0, rng = float(p50), _st(float(p90), float(p10))
        before = out[-1] if after_speaker else None
        out.append(
            _Feat(
                line=ln,
                who="client" if ln.who == "client" else "operator",
                start=start,
                end=end,
                overlap=overlap,
                f0=f0,
                range_st=rng,
                db=float(np.mean(tr.db[own])) if own.any() else None,
                pause=max(0.0, start - before.end) if before else None,
            )
        )
    return out


def _baseline(feats: list[_Feat]) -> dict[str, Any]:
    def mid(values: list[float | None]) -> float | None:
        vs = [v for v in values if v is not None]
        return median(vs) if vs else None

    return {
        "f0": mid([f.f0 for f in feats]),
        "db": mid([f.db for f in feats]),
        "wps": mid([f.wps for f in feats]),
        "lines": len(feats),
    }


def _flag(f: _Feat, prev: _Feat | None, base: dict[str, Any]) -> list[Flag]:
    flags: list[Flag] = []
    if base["lines"] >= MIN_BASELINE_LINES:
        higher = f.f0 is not None and base["f0"] and _st(f.f0, base["f0"]) >= RAISED_ST
        louder = f.db is not None and base["db"] is not None and f.db - base["db"] >= RAISED_DB
        if higher or louder:
            flags.append("raised")
    if f.range_st is not None and f.range_st < MONOTONE_ST and f.dur >= MONOTONE_MIN_S:
        flags.append("monotone")
    if base["lines"] >= MIN_BASELINE_LINES and f.wps >= max(FAST_RATIO * base["wps"], FAST_MIN_WPS):
        flags.append("fast")
    if prev is not None and prev.scored:
        reply = f.who == "operator" and prev.who == "client"
        if reply and f.pause is not None and f.pause >= LONG_PAUSE_S:
            flags.append("long_pause")
        if f.overlap >= OVERLAP_MIN_S:
            flags.append("overlap")
    return flags


def _runs(ns: list[int], order: list[int]) -> str:
    """«в реплике 4» или «в репликах 6–8, 12»: подряд — по порядку реплик этого говорящего."""
    at = {n: i for i, n in enumerate(order)}
    runs: list[list[int]] = []
    for n in ns:
        if runs and at[n] == at[runs[-1][-1]] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    text = ", ".join(f"{r[0]}–{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)
    return f"в реплике {text}" if len(ns) == 1 else f"в репликах {text}"


def _summary(feats: list[_Feat]) -> list[str]:
    out: list[str] = []
    for flag, phrase in PHRASE.items():
        for who in NAME:
            own = [f.line.n for f in feats if f.who == who and f.scored]
            hit = [f.line.n for f in feats if f.who == who and flag in f.flags]
            if hit:
                out.append(f"{phrase.format(who=NAME[who], other=OTHER[who])} {_runs(hit, own)}")
    out += [
        f"Пауза {round(f.pause or 0)} с перед ответом оператора (реплика {f.line.n})"
        for f in feats
        if "long_pause" in f.flags
    ]
    return out


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)


def analyse(lines: Sequence[Line | Fold], tracks: Tracks) -> dict[str, Any]:
    """`{"lines": [{n, f0, range_st, db, wps, pause, flags}], "speakers": {...}, "summary": [...]}`."""
    feats = _features(lines, tracks)
    base = {who: _baseline([f for f in feats if f.who == who and f.scored]) for who in NAME}
    for i, f in enumerate(feats):
        if f.scored:
            f.flags = _flag(f, feats[i - 1] if i else None, base[f.who])
    return {
        "lines": [
            {
                "n": f.line.n,
                "f0": None if f.f0 is None else round(f.f0),
                "range_st": _r(f.range_st),
                "db": _r(f.db),
                "wps": _r(f.wps),
                "pause": _r(f.pause),
                "flags": f.flags,
            }
            for f in feats
        ],
        "speakers": {who: {k: v if k == "lines" else _r(v) for k, v in b.items()} for who, b in base.items()},
        "summary": _summary(feats),
    }
