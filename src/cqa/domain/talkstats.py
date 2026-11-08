"""Статистика разговора и нормы команды. Чистый модуль.

Звонок — по отрезкам речи из разбора интонации (`prosody.analyse`), звук заново не разбирается.
Чат — по меткам времени реплик. Норма — границы Тьюки по диалогам того же канала.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby
from statistics import median, quantiles
from typing import Any, Final, Literal

from cqa.domain.ingest import ts_seconds
from cqa.domain.models import Fold, Line

MIN_N: Final = 5  # меньше диалогов — нормы нет
RULE: Final = (
    "Вне нормы — значение за границами Тьюки [Q1 − 1,5·IQR; Q3 + 1,5·IQR] по диалогам команды "
    f"того же канала; меньше {MIN_N} диалогов — нормы нет"
)
SCORED = ("conv", None)  # как в prosody: удержание и разговор с коллегой не считаются

Stats = Mapping[str, float | None]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str


CALL: Final = (
    Metric("operator_share", "Доля речи оператора", "%"),
    Metric("monologue_s", "Самый долгий монолог оператора", "с"),
    Metric("pause_median_s", "Пауза перед ответом оператора, медиана", "с"),
    Metric("pause_max_s", "Пауза перед ответом оператора, максимум", "с"),
    Metric("interrupt_operator", "Оператор перебил клиента", "раз"),
    Metric("interrupt_client", "Клиент перебил оператора", "раз"),
    Metric("silence_share", "Доля тишины", "%"),
    Metric("wps_operator", "Темп оператора", "сл/с"),
    Metric("wps_client", "Темп клиента", "сл/с"),
)
CHAT: Final = (
    Metric("reply_median_s", "Время ответа оператора, медиана", "с"),
    Metric("reply_max_s", "Время ответа оператора, максимум", "с"),
)


@dataclass(frozen=True)
class Span:
    """Речь реплики в записи, с; `interrupt` — флаг `overlap` разбора, `scored` — реплика `conv`."""

    who: Literal["client", "operator"]
    start: float
    end: float
    words: int
    interrupt: bool = False
    scored: bool = True

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


def _share(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole > 0 else None


def call_stats(spans: Sequence[Span]) -> dict[str, float | None]:
    """Метрики `CALL` по участкам `conv` подряд: удержание делит звонок, его тишина не считается."""
    blocks = [list(g) for k, g in groupby(spans, key=lambda s: s.scored) if k]
    own = [s for b in blocks for s in b]
    talk = {w: sum(s.dur for s in own if s.who == w) for w in ("operator", "client")}
    words = {w: sum(s.words for s in own if s.who == w) for w in ("operator", "client")}
    pauses: list[float] = []
    monologue = speech = total = 0.0
    for b in blocks:
        cursor = run_start = b[0].start
        for i, s in enumerate(b):
            speech += max(0.0, s.end - max(s.start, cursor))
            cursor = max(cursor, s.end)
            prev = b[i - 1] if i else None
            if s.who == "operator":
                # ponytail: любое «угу» клиента прерывает монолог; порог поддакивания — по разметке КК
                if prev is None or prev.who != "operator":
                    run_start = s.start
                monologue = max(monologue, s.end - run_start)
                if prev is not None and prev.who == "client":
                    pauses.append(max(0.0, s.start - prev.end))
        total += cursor - b[0].start
    return {
        "operator_share": _share(talk["operator"], talk["operator"] + talk["client"]),
        "monologue_s": _r(monologue) if talk["operator"] else None,
        "pause_median_s": _r(median(pauses)) if pauses else None,
        "pause_max_s": _r(max(pauses)) if pauses else None,
        "interrupt_operator": sum(s.interrupt for s in own if s.who == "operator") if own else None,
        "interrupt_client": sum(s.interrupt for s in own if s.who == "client") if own else None,
        "silence_share": _share(total - speech, total),
        "wps_operator": _r(words["operator"] / talk["operator"]) if talk["operator"] else None,
        "wps_client": _r(words["client"] / talk["client"]) if talk["client"] else None,
    }


def chat_stats(lines: Sequence[Line | Fold]) -> dict[str, float | None] | None:
    """Метрики `CHAT`: от первого неотвеченного сообщения клиента до ответа оператора, только `conv`.

    None — нет ни одного ответа с разобранными метками.
    """
    delays: list[float] = []
    waiting: float | None = None
    for ln in lines:
        if not isinstance(ln, Line) or ln.seg not in SCORED or ln.who not in ("client", "operator"):
            continue
        at = ts_seconds(str(ln.t))
        if at is None:
            continue
        if ln.who == "client":
            waiting = at if waiting is None else waiting
        elif waiting is not None:
            if at >= waiting:
                delays.append(at - waiting)
            waiting = None
    if not delays:
        return None
    return {"reply_median_s": _r(median(delays)), "reply_max_s": _r(max(delays))}


def norms(rows: Sequence[Stats], metrics: Sequence[Metric]) -> dict[str, Any]:
    """`{n, note, metrics: [{key, label, unit, n, median, q1, q3, iqr, lo, hi}]}` по диалогам канала."""
    out = []
    for m in metrics:
        vs = [v for r in rows if (v := r.get(m.key)) is not None]
        fences: dict[str, float | None] = dict.fromkeys(("q1", "q3", "iqr", "lo", "hi"))
        if len(vs) >= MIN_N:
            q1, _, q3 = quantiles(vs, n=4, method="inclusive")
            iqr = q3 - q1
            fences = {"q1": q1, "q3": q3, "iqr": iqr, "lo": q1 - 1.5 * iqr, "hi": q3 + 1.5 * iqr}
        row = {"key": m.key, "label": m.label, "unit": m.unit, "n": len(vs)}
        out.append(row | {k: _r(v) for k, v in {"median": median(vs) if vs else None, **fences}.items()})
    note = None if len(rows) >= MIN_N else f"недостаточно данных: {len(rows)} из {MIN_N} диалогов"
    return {"n": len(rows), "note": note, "metrics": out}


def mark(stats: Stats, section: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Метрики диалога с медианой команды; `out_of_norm` — None, если нет значения или нормы."""
    out = []
    for m in section["metrics"]:
        value = stats.get(m["key"])
        outside = None if value is None or m["lo"] is None else not m["lo"] <= value <= m["hi"]
        keep = {k: m[k] for k in ("key", "label", "unit", "median", "lo", "hi")}
        out.append(keep | {"value": value, "out_of_norm": outside})
    return out
