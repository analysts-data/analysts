"""Расширенная аналитика: тренд, тепловая карта, драйверы, распределения, срезы, апелляции, сигналы модели.

Чистые функции над текущим состоянием, как в GET /api/state: ответ пары — с учётом последнего решения
(`effective_answer`), итог — `scoring.total`, доля — `frac`. Каждый ответ несёт n по ячейкам, отметку
`low_n` и точные формулы в `definitions`: эвристик и баллов без объяснения нет.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from statistics import StatisticsError, correlation, fmean, median
from typing import Any

from cqa.domain.models import Answer, Appeal, Checklist, Criterion, Dialog
from cqa.domain.report import CHANNEL
from cqa.domain.review import allowed_answers, effective_answer, needs_review
from cqa.domain.scoring import frac, r2, total

MIN_N = 5
NAMES = ("trend", "heatmap", "drivers", "distribution", "crosstab", "appeals", "model")
BY = {"trend": ("day", "week"), "heatmap": ("operator", "product", "lang", "ch"), "model": ("day", "week")}
UNSET = "Не указан"
DECIDED = ("confirmed", "changed")


@dataclass(frozen=True)
class Filters:
    lang: str | None = None
    ch: str | None = None
    operator: str | None = None
    product: str | None = None
    since: date | None = None
    until: date | None = None


NO_FILTERS = Filters()


@dataclass(frozen=True)
class _Row:
    d: Dialog
    ans: dict[str, Answer]  # ответы с учётом решений
    total: float


# --- Определения: формула каждой метрики, по-русски ---

DEFS = {
    "n": (
        "n — число оценённых диалогов выборки: диалоги после фильтров, у которых есть итог (хотя бы один "
        "применимый критерий с ответом). У ячейки n — число наблюдений, из которых она посчитана."
    ),
    "low_n": f"low_n = true, если n ячейки меньше {MIN_N} (min_n). При n ≤ {MIN_N - 1} один диалог "
    f"сдвигает долю минимум на {100 // (MIN_N - 1)} п. п. (1/n ≥ 1/{MIN_N - 1}); значение показано, "
    "но сравнивать и делать выводы по нему нельзя. Порог — договорённость о минимальном объёме, "
    "а не статистический тест.",
    "filters": (
        "lang — язык без учёта регистра; ch — канал; operator, product — точное совпадение поля диалога "
        "(нет поля — нет совпадений); since, until — дата диалога включительно. Апелляции и решения — "
        "только по выбранным диалогам."
    ),
    "date": (
        "Дата диалога — день из `at` (время Астаны, ДД.ММ ЧЧ:ММ; у звонка — первое событие, у чата — "
        "загрузка набора). Года в `at` нет: берётся текущий год, а дата позже сегодняшней — прошлого "
        "года."
    ),
    "answer": (
        "Ответ пары (диалог, критерий) — `to` последнего решения по апелляции или проверке (confirmed или"
        " changed) текущего смысла критерия, иначе ответ модели."
    ),
    "avg_total": (
        "Средний итог = Σ итогов / n. Итог диалога = 100 × Σ(вес × доля) / Σ(вес применимых критериев); "
        "N/A, флаги и критерии без ответа не входят (design/contract.md, «Итог»)."
    ),
    "share": (
        "Доля балла критерия: да = 1, нет = 0, шкала = ступень / верхняя ступень. Средняя доля = Σ долей "
        "/ n, n — число применимых ответов (N/A не входит)."
    ),
    "gross": (
        "Грубое нарушение — диалог, где хотя бы один вопрос критерия-флага отмечен «да». share = k / n: k"
        " — такие диалоги, n — оценённые диалоги."
    ),
    "no_next_step": (
        "Нет следующего шага — у критерия с signal = resolution доля балла меньше 1. share = k / n."
    ),
    "needs_review": (
        "Нужна проверка — диалог не отмечен проверенным, и у критерия bool или scale второе мнение "
        "расходится с ответом (alt ≠ a) или основание не подтвердилось (evFail), а решения по паре нет. "
        "share = k / n."
    ),
    "period": (
        "by = day — дата диалога (period = ГГГГ-ММ-ДД); by = week — ISO-неделя с понедельника (period = "
        "ГГГГ-Wнн, start — понедельник). Периоды без диалогов не выводятся."
    ),
    "rows": (
        "Строки — значения поля диалога by (operator, product, lang, ch); диалоги без значения — строка "
        "«Не указан». Ячейка — средняя доля балла критерия по применимым ответам строки, n — их число; "
        "columns — то же по всей выборке."
    ),
    "at_max": (
        "at_max — диалоги, где критерий применим и его доля = 1; below_max — доля < 1. avg_total — "
        "средний итог группы, gross — доля грубых нарушений в группе, n — размер группы."
    ),
    "gap": (
        "gap = avg_total(at_max) − avg_total(below_max), разница средних в баллах из 100. Это связь, а не"
        " причина: критерий сам входит в итог со своим весом. low_n — если любая из групп меньше min_n."
    ),
    "r": (
        "r — корреляция Пирсона доли балла критерия с итогом по диалогам, где критерий применим "
        "(statistics.correlation, n — их число); у критерия да/нет это точечно-бисериальная корреляция. "
        "null, если n < 2 или одна из величин постоянна."
    ),
    "lowest": (
        "lowest — диалоги, где доля балла критерия минимальна среди применимых критериев диалога и меньше"
        " 1; при равенстве засчитывается каждому из равных. share = k / n оценённых диалогов."
    ),
    "uplift": (
        "Симуляция: в каждом диалоге, где критерий применим, ответ заменяется верхним (да или верхняя "
        "ступень), итог пересчитывается той же формулой; N/A не меняется. avg_total_if_max — средний итог"
        " после, uplift = avg_total_if_max − средний итог до. Сортировка — по uplift, затем по gap."
    ),
    "totals": (
        "Гистограмма итогов: корзины [0; 10), [10; 20), …, [90; 100], последняя включает 100. share = n "
        "корзины / n."
    ),
    "answers": (
        "Ответы критерия по оценённым диалогам: да, нет, N/A или ступени шкалы; share = n ответа / n "
        "ответов критерия (N/A входит). У флага — число диалогов, где вопрос отмечен «да», из n ответов "
        "флага."
    ),
    "cells": (
        "Сочетание канал × язык × продукт (product = null — поле не задано); n — оценённые диалоги "
        "сочетания, avg_total и gross — как выше. Порядок — по n, затем по первому появлению."
    ),
    "decisions": (
        "filed — апелляции оператора (kind = appeal), reviews — проверки специалиста (kind = review); "
        "pending — на рассмотрении, closed — закрыты без решения, decided — статус confirmed или changed "
        "(обоих видов, решения прежнего смысла критерия не входят)."
    ),
    "changed_share": (
        "changed_share = changed / decided: доля решений, изменивших ответ. Высокая доля у критерия — "
        "сигнал, что формулировка неоднозначна или модель его путает; low_n — если decided < min_n."
    ),
    "median_hours": (
        "median_hours — медиана (statistics.median) часов от подачи (at) до решения (decidedAt) по "
        "решённым апелляциям, timed — их число; проверки не входят: их решение — в момент записи."
    ),
    "reviewers": (
        "По проверяющему (поле reviewer): decided, changed, changed_share, median_hours — как выше."
    ),
    "results": (
        "Сигналы модели — по сырым результатам (без решений) выбранных диалогов, у которых результаты "
        "есть; k — число результатов с признаком, n — знаменатель метрики."
    ),
    "second_opinion": ("second_opinion — согласие второго мнения: n — результаты с alt, k — где alt = a."),
    "ev_fail": (
        "ev_fail — основание не подтвердилось: n — результаты основной модели (не Jev и не вручную), k — "
        "с evFail."
    ),
    "jev_unsure": (
        "jev_unsure — низкая уверенность Jev: n — результаты Jev (model = {jev}), k — с evFail; у Jev "
        "evFail ставится, когда вероятность ответа ниже порога JEV_SURE или не возвращена."
    ),
    "manual": ("manual — ручные ответы специалиста: n — все результаты критерия, k — с model = «{manual}»."),
    "cost": (
        "Стоимость и время на диалог по периодам: avg_usd = Σ cost.usd / n, avg_s = Σ cost.ms / 1000 / n;"
        " n — диалоги периода с данными о стоимости."
    ),
}
COMMON = ("n", "low_n", "filters", "answer")
KEYS = {
    "trend": (*COMMON, "date", "period", "avg_total", "share", "gross", "no_next_step", "needs_review"),
    "heatmap": (*COMMON, "rows", "avg_total", "share"),
    "drivers": (*COMMON, "avg_total", "share", "gross", "at_max", "gap", "r", "lowest", "uplift"),
    "distribution": (*COMMON, "totals", "answers"),
    "crosstab": (*COMMON, "cells", "avg_total", "gross"),
    "appeals": ("n", "low_n", "filters", "decisions", "changed_share", "median_hours", "reviewers"),
    "model": (
        "n",
        "low_n",
        "filters",
        "date",
        "period",
        "results",
        "second_opinion",
        "ev_fail",
        "jev_unsure",
        "manual",
        "cost",
    ),
}


# --- Общие части ---


def day(at: str, today: date) -> date:
    """`at` «ДД.ММ ЧЧ:ММ» без года: последняя такая дата не позже сегодня (29.02 — ближайший високосный)."""
    dd, mm = int(at[:2]), int(at[3:5])
    for y in range(today.year, today.year - 8, -1):
        try:
            d = date(y, mm, dd)
        except ValueError:
            continue
        if d <= today:
            return d
    raise ValueError(f"Дата {at!r} не разобрана")


def _moment(at: str, today: date) -> datetime:
    return datetime.combine(day(at, today), datetime.strptime(at[6:11], "%H:%M").time())


def _share(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def _count(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "share": _share(k, n), "low_n": n < MIN_N}


def _cell(fs: Sequence[float]) -> dict[str, Any]:
    return {"n": len(fs), "share": round(fmean(fs), 4) if fs else None, "low_n": len(fs) < MIN_N}


def _avg(xs: Sequence[float]) -> float | None:
    return r2(fmean(xs)) if xs else None


def _field(d: Dialog, name: str) -> str | None:
    # ponytail: operator и product добавляют соседние ветки; без поля — None, фильтр ничего не находит
    value = getattr(d, name, None)
    return None if value is None else str(value)


def _pick(dialogs: Sequence[Dialog], f: Filters, today: date) -> list[Dialog]:
    lang = f.lang.upper() if f.lang else None

    def ok(d: Dialog) -> bool:
        if lang not in (None, d.lang.upper()) or f.ch not in (None, d.ch):
            return False
        if any(
            want is not None and _field(d, k) != want
            for k, want in (("operator", f.operator), ("product", f.product))
        ):
            return False
        if f.since or f.until:
            x = day(d.at, today)
            return not (f.since and x < f.since or f.until and x > f.until)
        return True

    return [d for d in dialogs if ok(d)]


def _rows(checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]) -> list[_Row]:
    rows = []
    for d in dialogs:
        ans = {
            cid: effective_answer(r, [a for a in appeals if a.dlg == d.id and a.cid == cid])
            for cid, r in d.res.items()
        }
        if (t := total(checklist, ans)) is not None:
            rows.append(_Row(d, ans, t))
    return rows


def _fr(c: Criterion, ans: dict[str, Answer]) -> float | None:
    a = ans.get(c.id)
    return None if a is None else frac(c, a)


def _gross(checklist: Checklist, ans: dict[str, Answer]) -> bool:
    return any(
        isinstance(a := ans.get(c.id), dict) and any(a.values())
        for c in checklist.criteria
        if c.type == "flag"
    )


def _scored(checklist: Checklist) -> list[Criterion]:
    return [c for c in checklist.criteria if c.type != "flag"]


def _groups[T](rows: Iterable[T], key: Callable[[T], Any]) -> dict[Any, list[T]]:
    out: dict[Any, list[T]] = {}
    for r in rows:
        out.setdefault(key(r), []).append(r)
    return out


def _period(d: date, by: str) -> tuple[str, str]:
    if by == "day":
        return d.isoformat(), d.isoformat()
    y, w, wd = d.isocalendar()
    return f"{y}-W{w:02d}", (d - timedelta(days=wd - 1)).isoformat()


# --- Отчёты ---


def _trend(
    checklist: Checklist, rows: list[_Row], appeals: Sequence[Appeal], by: str, today: date
) -> dict[str, Any]:
    cs = _scored(checklist)
    decided = {(a.dlg, a.cid) for a in appeals if a.status in DECIDED}

    def review(r: _Row) -> bool:
        return not r.d.reviewed and any(
            (x := r.d.res.get(c.id)) is not None and needs_review(c, x) and (r.d.id, c.id) not in decided
            for c in cs
        )

    periods = _groups(rows, lambda r: _period(day(r.d.at, today), by))
    points = []
    for (period, start), rs in sorted(periods.items()):
        n = len(rs)
        point: dict[str, Any] = {
            "period": period,
            "n": n,
            "low_n": n < MIN_N,
            "avg_total": _avg([r.total for r in rs]),
        }
        if by == "week":
            point["start"] = start
        point["gross"] = _count(sum(_gross(checklist, r.ans) for r in rs), n)
        lost = [
            r
            for r in rs
            if any(c.signal == "resolution" and (f := _fr(c, r.ans)) is not None and f < 1 for c in cs)
        ]
        point["no_next_step"] = _count(len(lost), n)
        point["needs_review"] = _count(sum(map(review, rs)), n)
        point["criteria"] = {c.id: _cell([f for r in rs if (f := _fr(c, r.ans)) is not None]) for c in cs}
        points.append(point)
    return {"criteria": [{"id": c.id, "name": c.name} for c in cs], "points": points}


def _heatmap(checklist: Checklist, rows: list[_Row], by: str) -> dict[str, Any]:
    cs = _scored(checklist)
    label = CHANNEL if by == "ch" else {}
    out = []
    for key, rs in sorted(_groups(rows, lambda r: _field(r.d, by)).items(), key=lambda kv: -len(kv[1])):
        out.append(
            {
                "key": key,
                "label": UNSET if key is None else label.get(key, key),
                "n": len(rs),
                "low_n": len(rs) < MIN_N,
                "avg_total": _avg([r.total for r in rs]),
                "cells": {c.id: _cell([f for r in rs if (f := _fr(c, r.ans)) is not None]) for c in cs},
            }
        )
    columns = []
    for c in cs:
        cell = _cell([f for r in rows if (f := _fr(c, r.ans)) is not None])
        columns.append({"id": c.id, "name": c.name, "n": cell["n"], "share": cell["share"]})
    return {"columns": columns, "rows": out}


def _top(c: Criterion) -> Answer:
    return "yes" if c.type == "bool" else max(c.steps or [0])


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _drivers(checklist: Checklist, rows: list[_Row]) -> dict[str, Any]:
    base = fmean(r.total for r in rows) if rows else None
    out: list[dict[str, Any]] = []
    for c in _scored(checklist):
        pairs = [(f, r) for r in rows if (f := _fr(c, r.ans)) is not None]
        top = [r for f, r in pairs if f == 1]
        low = [r for f, r in pairs if f < 1]

        def group(rs: list[_Row]) -> dict[str, Any]:
            return {
                "n": len(rs),
                "avg_total": _avg([r.total for r in rs]),
                "gross": _share(sum(_gross(checklist, r.ans) for r in rs), len(rs)),
            }

        gap = r2(fmean(r.total for r in top) - fmean(r.total for r in low)) if top and low else None
        try:
            rho: float | None = round(correlation([f for f, _ in pairs], [r.total for _, r in pairs]), 4)
        except StatisticsError:
            rho = None
        lowest = 0
        for r in rows:
            fs = {x.id: f for x in _scored(checklist) if (f := _fr(x, r.ans)) is not None}
            lowest += c.id in fs and fs[c.id] < 1 and fs[c.id] == min(fs.values())
        after: float | None = None
        uplift: float | None = None
        what_if = None
        if base is not None:
            moved = [
                total(checklist, {**r.ans, c.id: _top(c)}) if _fr(c, r.ans) is not None else r.total
                for r in rows
            ]
            mean_after = fmean(t for t in moved if t is not None)
            after, uplift = r2(mean_after), r2(mean_after - base)
            what_if = (
                f"Если поднять «{c.name}» до максимума во всех {len(pairs)} диалогах, где он применим, "
                f"средний итог вырастет на {_num(uplift)} балла: с {_num(r2(base))} до {_num(after)}."
            )
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "n": len(pairs),
                "at_max": group(top),
                "below_max": group(low),
                "gap": gap,
                "low_n": len(top) < MIN_N or len(low) < MIN_N,
                "r": rho,
                "lowest": _count(lowest, len(rows)),
                "uplift": uplift,
                "avg_total_if_max": after,
                "what_if": what_if,
            }
        )
    out.sort(key=lambda x: (-(x["uplift"] or 0), -(x["gap"] or 0)))
    return {"base": _avg([r.total for r in rows]), "drivers": out}


def _distribution(checklist: Checklist, rows: list[_Row]) -> dict[str, Any]:
    n = len(rows)
    bins = []
    for lo in range(0, 100, 10):
        k = sum(lo <= r.total < lo + 10 or (lo == 90 and r.total == 100) for r in rows)
        bins.append({"lo": lo, "hi": lo + 10, "n": k, "share": _share(k, n)})
    crit = []
    for c in checklist.criteria:
        answers: list[dict[str, Any]]
        given = [a for r in rows if (a := r.ans.get(c.id)) is not None]
        if c.type == "flag":
            answers = [
                {
                    "a": q.k,
                    "label": q.label,
                    "n": (k := sum(isinstance(a, dict) and bool(a.get(q.k)) for a in given)),
                    "share": _share(k, len(given)),
                }
                for q in c.questions or []
            ]
        else:
            answers = [
                {"a": v, "n": (k := sum(a == v for a in given)), "share": _share(k, len(given))}
                for v in allowed_answers(c)
            ]
        crit.append({"id": c.id, "name": c.name, "type": c.type, "n": len(given), "answers": answers})
    return {"totals": bins, "criteria": crit}


def _crosstab(checklist: Checklist, rows: list[_Row]) -> dict[str, Any]:
    groups = _groups(rows, lambda r: (r.d.ch, r.d.lang.upper(), _field(r.d, "product")))
    cells = [
        {
            "ch": ch,
            "lang": lang,
            "product": product,
            "n": len(rs),
            "low_n": len(rs) < MIN_N,
            "avg_total": _avg([r.total for r in rs]),
            "gross": _count(sum(_gross(checklist, r.ans) for r in rs), len(rs)),
        }
        for (ch, lang, product), rs in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    ]
    return {"cells": cells}


def _hours(appeals: Sequence[Appeal], today: date) -> list[float]:
    return [
        (_moment(a.decidedAt, today) - _moment(a.at, today)).total_seconds() / 3600
        for a in appeals
        if a.kind == "appeal" and a.status in DECIDED and a.decidedAt
    ]


def _decisions(appeals: Sequence[Appeal], today: date) -> dict[str, Any]:
    decided = [a for a in appeals if a.status in DECIDED]
    changed = sum(a.status == "changed" for a in decided)
    hours = _hours(appeals, today)
    return {
        "decided": len(decided),
        "changed": changed,
        "changed_share": _share(changed, len(decided)),
        "low_n": len(decided) < MIN_N,
        "median_hours": round(median(hours), 2) if hours else None,
        "timed": len(hours),
    }


def _appeals(checklist: Checklist, appeals: Sequence[Appeal], today: date) -> dict[str, Any]:
    decided = [a for a in appeals if a.status in DECIDED]
    summary = {
        "filed": sum(a.kind == "appeal" for a in appeals),
        "reviews": sum(a.kind == "review" for a in appeals),
        "pending": sum(a.status == "pending" for a in appeals),
        "closed": sum(a.status == "closed" for a in appeals),
        "decided": len(decided),
        "changed": sum(a.status == "changed" for a in decided),
        "confirmed": sum(a.status == "confirmed" for a in decided),
    }
    d = _decisions(appeals, today)
    summary |= {k: d[k] for k in ("changed_share", "low_n", "median_hours", "timed")}
    crit: list[dict[str, Any]] = []
    for c in checklist.criteria:
        mine = [a for a in appeals if a.cid == c.id]
        if not mine:
            continue
        dc = [a for a in mine if a.status in DECIDED]
        changed = sum(a.status == "changed" for a in dc)
        crit.append(
            {
                "id": c.id,
                "name": c.name,
                "filed": sum(a.kind == "appeal" for a in mine),
                "reviews": sum(a.kind == "review" for a in mine),
                "decided": len(dc),
                "changed": changed,
                "confirmed": len(dc) - changed,
                "changed_share": _share(changed, len(dc)),
                "low_n": len(dc) < MIN_N,
            }
        )
    crit.sort(key=lambda x: -1 if x["changed_share"] is None else -x["changed_share"])
    by = _groups(decided, lambda a: a.reviewer or UNSET)
    reviewers = [{"reviewer": who, **_decisions(rs, today)} for who, rs in by.items()]
    reviewers.sort(key=lambda x: -x["decided"])
    return {"summary": summary, "criteria": crit, "reviewers": reviewers}


def _model(
    checklist: Checklist, dialogs: Sequence[Dialog], by: str, today: date, jev: str, manual: str
) -> dict[str, Any]:
    crit = []
    for c in checklist.criteria:
        res = [r for d in dialogs if (r := d.res.get(c.id)) is not None]
        alt = [r for r in res if r.alt is not None]
        own = [r for r in res if r.model not in (jev, manual)]
        mine = [r for r in res if r.model == jev]
        crit.append(
            {
                "id": c.id,
                "name": c.name,
                "results": len(res),
                "second_opinion": _count(sum(r.alt == r.a for r in alt), len(alt)),
                "ev_fail": _count(sum(r.evFail for r in own), len(own)),
                "jev_unsure": _count(sum(r.evFail for r in mine), len(mine)),
                "manual": _count(sum(r.model == manual for r in res), len(res)),
            }
        )
    paid = [d for d in dialogs if d.cost]
    cost = []
    for (period, _), ds in sorted(_groups(paid, lambda d: _period(day(d.at, today), by)).items()):
        n = len(ds)
        cost.append(
            {
                "period": period,
                "n": n,
                "avg_usd": round(fmean(d.cost.usd for d in ds if d.cost), 4),
                "avg_s": round(fmean(d.cost.ms for d in ds if d.cost) / 1000, 1),
                "low_n": n < MIN_N,
            }
        )
    return {"criteria": crit, "cost": cost}


def build(
    name: str,
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    *,
    today: date,
    filters: Filters = NO_FILTERS,
    by: str | None = None,
    jev: str = "",
    manual: str = "",
) -> dict[str, Any]:
    """`dialogs` с текущими `res`, `appeals` — как в GET /api/state. `by` — из BY[name], без него — первый."""
    picked = _pick(dialogs, filters, today)
    ids = {d.id for d in picked}
    appeals = [a for a in appeals if a.dlg in ids]
    rows = _rows(checklist, picked, appeals)
    by = by or BY.get(name, ("",))[0]
    body: dict[str, Any]
    if name == "trend":
        body = _trend(checklist, rows, appeals, by, today)
    elif name == "heatmap":
        body = _heatmap(checklist, rows, by)
    elif name == "drivers":
        body = _drivers(checklist, rows)
    elif name == "distribution":
        body = _distribution(checklist, rows)
    elif name == "crosstab":
        body = _crosstab(checklist, rows)
    elif name == "appeals":
        body = _appeals(checklist, appeals, today)
    else:
        with_res = [d for d in picked if d.res]
        body = _model(checklist, with_res, by, today, jev, manual)
    flt = {k: v.isoformat() if isinstance(v, date) else v for k, v in asdict(filters).items()}
    if flt["lang"]:
        flt["lang"] = flt["lang"].upper()
    definitions = {k: DEFS[k].format(jev=jev, manual=manual) for k in KEYS[name]}
    head = {"name": name, "filters": flt, "by": by or None, "n": len(rows), "min_n": MIN_N}
    return {**head, **body, "definitions": definitions}
