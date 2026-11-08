"""Отчёт для руководства: ключевые числа, критерии, причины, каналы и языки, выводы. Чистые функции.

Ответ пары — с учётом последнего решения (`effective_answer`), итог — `scoring.total`, доля — `frac`:
те же числа, что видит интерфейс.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from cqa.domain.models import Answer, Appeal, Checklist, Criterion, Dialog
from cqa.domain.review import awaits_review, effective_answer
from cqa.domain.scoring import frac, r2, total
from cqa.domain.tables import CSS as TABLE_CSS
from cqa.domain.tables import Doc, md_cell, page
from cqa.domain.tables import Table as Rows
from cqa.domain.tables import to_csv as doc_csv

TOP = 10
CHANNEL = {"chat": "Чат", "call": "Звонок"}
NOBODY = "Не назначено"
EMPTY = "Нет оценённых диалогов"
NOTE = (
    "Итог — с учётом решений по апелляциям и проверкам. Грубые нарушения в итог не входят. "
    "Доля баллов критерия считается среди применимых оценок, N/A показан отдельно."
)


def _lost(c: Criterion, a: Answer | None) -> bool:
    f = None if a is None else frac(c, a)
    return f is not None and f < 1


def _share(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def _groups(rows: Sequence[tuple[str, float]], label: Mapping[str, str]) -> list[dict[str, Any]]:
    """Средний итог и число диалогов по ключу; больше диалогов — выше, при равенстве порядок набора."""
    keys = dict.fromkeys(k for k, _ in rows)
    out = []
    for key in keys:
        ts = [t for k, t in rows if k == key]
        out.append({"key": key, "label": label.get(key, key), "n": len(ts), "avg": r2(sum(ts) / len(ts))})
    return sorted(out, key=lambda g: -g["n"])


Row = tuple[Dialog, dict[str, Answer], float]  # оценённый диалог: ответы с учётом решений, итог


def _status(d: Dialog) -> str:
    return d.sufficiency.status if d.sufficiency else "ok"


def _scored(checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]) -> list[Row]:
    rows: list[Row] = []
    for d in dialogs:
        if _status(d) == "block":  # «Недостаточно данных»: вне средних даже с прежними ответами, виден счёт
            continue
        answers = {
            cid: effective_answer(r, [a for a in appeals if a.dlg == d.id and a.cid == cid])
            for cid, r in d.res.items()
        }
        if (t := total(checklist, answers)) is not None:
            rows.append((d, answers, t))
    return rows


def _summary(
    checklist: Checklist,
    picked: Sequence[Dialog],
    rows: Sequence[Row],
    appeals: Sequence[Appeal],
    owners: Mapping[str, str],
) -> dict[str, Any]:
    """summary, criteria, reasons, channels, langs по выбранным диалогам; `appeals` — только их."""
    decided = {(a.dlg, a.cid) for a in appeals if a.status in ("confirmed", "changed")}
    scored_cs = [c for c in checklist.criteria if c.type != "flag"]
    questions = [(fc.id, q) for fc in checklist.criteria if fc.type == "flag" for q in fc.questions or []]
    n = len(rows)

    def found(answers: dict[str, Answer], cid: str, k: str) -> bool:
        a = answers.get(cid)
        return isinstance(a, dict) and bool(a.get(k))

    flagged = sum(any(found(ans, cid, q.k) for cid, q in questions) for _, ans, _ in rows)
    no_next = sum(
        any(c.signal == "resolution" and _lost(c, ans.get(c.id)) for c in scored_cs) for _, ans, _ in rows
    )
    review = sum(awaits_review(scored_cs, d, decided) for d, _, _ in rows)
    costs = [d.cost for d, _, _ in rows if d.cost]

    criteria: list[dict[str, Any]] = []
    for c in scored_cs:
        fs = [f for _, ans, _ in rows if (a := ans.get(c.id)) is not None and (f := frac(c, a)) is not None]
        if fs:
            na = sum(ans.get(c.id) == "na" for _, ans, _ in rows)
            criteria.append(
                {"id": c.id, "name": c.name, "n": len(fs), "na": na, "share": round(sum(fs) / len(fs), 4)}
            )
    criteria.sort(key=lambda x: x["share"])

    reasons: dict[str, tuple[set[str], list[str]]] = {}  # tag -> (диалоги, названия критериев)
    for d, ans, _ in rows:
        for c in scored_cs:
            r = d.res.get(c.id)
            if r and r.tag and _lost(c, ans.get(c.id)):
                ds, names = reasons.setdefault(r.tag, (set(), []))
                ds.add(d.id)
                if c.name not in names:
                    names.append(c.name)
    top = sorted(reasons.items(), key=lambda kv: -len(kv[1][0]))[:TOP]

    return {
        "summary": {
            "dialogs": len(picked),
            "scored": n,
            "avg_total": r2(sum(t for _, _, t in rows) / n) if n else None,
            "risk": {
                "dialogs": flagged,
                "share": _share(flagged, n),
                "kinds": [
                    {"k": q.k, "label": q.label, "n": sum(found(ans, cid, q.k) for _, ans, _ in rows)}
                    for cid, q in questions
                ],
            },
            "no_next_step": {"dialogs": no_next, "share": _share(no_next, n)},
            "needs_review": review,
            "insufficient": sum(_status(d) == "block" for d in picked),
            "low_data": sum(_status(d) == "flag" for d, _, _ in rows),
            "open_appeals": sum(a.status == "pending" for a in appeals),
            "cost": {
                "dialogs": len(costs),
                "avg_usd": round(sum(c.usd for c in costs) / len(costs), 4) if costs else None,
                "avg_s": round(sum(c.ms for c in costs) / len(costs) / 1000, 1) if costs else None,
            },
        },
        "criteria": criteria,
        "reasons": [
            {"tag": tag, "dialogs": len(ds), "owner": owners.get(tag, NOBODY), "criteria": names}
            for tag, (ds, names) in top
        ],
        "channels": _groups([(d.ch, t) for d, _, t in rows], CHANNEL),
        "langs": _groups([(d.lang, t) for d, _, t in rows], {}),
    }


def build_report(
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    owners: Mapping[str, str],
    *,
    at: str,
    lang: str | None = None,
    ch: str | None = None,
    operator: str | None = None,
) -> dict[str, Any]:
    """`dialogs` с текущими `res`, `appeals` — как в GET /api/state. Фильтры необязательны."""
    lang = lang.upper() if lang else None
    picked = [
        d
        for d in dialogs
        if lang in (None, d.lang.upper()) and ch in (None, d.ch) and operator in (None, d.operator or UNKNOWN)
    ]
    ids = {d.id for d in picked}
    appeals = [a for a in appeals if a.dlg in ids]
    rep: dict[str, Any] = {
        "at": at,
        "filters": {"lang": lang, "ch": ch, "operator": operator},
        **_summary(checklist, picked, _scored(checklist, picked, appeals), appeals, owners),
        "operators": _section(checklist, picked, appeals),
    }
    rep["findings"] = _findings(
        rep, any(c.type != "flag" and c.signal == "resolution" for c in checklist.criteria)
    )
    return rep


# --- По сотрудникам ---

UNKNOWN = "Не указан"  # группа диалогов без сотрудника
ATTENTION, STRENGTHS = 5, 3
_CARD_ONLY = ("dialog_ids", "reasons")
# Сравнивать сотрудников можно только от 5 оценённых диалогов: при n = 4 одна оценка сдвигает среднее
# на четверть шкалы, а 95 % интервал среднего — ±1,6 стандартного отклонения (t(0,975; 3) = 3,18).
MIN_SCORED = 5
# t(0,975; df) распределения Стьюдента, df = 1..30; дальше — разложение Корниша — Фишера (точность 1e-4)
_T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
    2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip
DEFINITIONS = {
    "n": "оценённые диалоги сотрудника: есть итог с учётом решений по апелляциям",
    "avg_total": "средний итог n оценённых диалогов",
    "sd": "выборочное стандартное отклонение итога (делитель n − 1); при n < 2 — null",
    "ci95": "95 % доверительный интервал среднего итога по Стьюденту: среднее ± t(0,975; n − 1) · sd / √n, "
    "обрезан до шкалы 0–100; при n < 2 — null",
    "ranked": f"в порядке «требуют внимания» только сотрудники с n ≥ {MIN_SCORED}: при меньшем n одна оценка "
    "сдвигает среднее на четверть шкалы и больше, а интервал шире любой разницы между сотрудниками; "
    "диалоги без сотрудника не ранжируются",
    "order": "сначала ранжированные по возрастанию среднего итога (кому нужна помощь — выше), "
    "затем остальные по убыванию n",
}


def _t95(df: int) -> float:
    if df <= len(_T95):
        return _T95[df - 1]
    z = 1.959964
    return z + (z**3 + z) / (4 * df) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)


def ci95(totals: Sequence[float]) -> tuple[float | None, list[float] | None]:
    """Выборочное стандартное отклонение и 95 % интервал среднего по Стьюденту; при n < 2 — (None, None)."""
    n = len(totals)
    if n < 2:
        return None, None
    sd = statistics.stdev(totals)
    mean, half = sum(totals) / n, _t95(n - 1) * sd / math.sqrt(n)
    return r2(sd), [r2(max(0.0, mean - half)), r2(min(100.0, mean + half))]


def _operator(
    checklist: Checklist, name: str, mine: list[Dialog], appeals: Sequence[Appeal], owners: Mapping[str, str]
) -> dict[str, Any]:
    ids = {d.id for d in mine}
    own = [a for a in appeals if a.dlg in ids]
    rows = _scored(checklist, mine, own)
    core = _summary(checklist, mine, rows, own, owners)
    s = core["summary"]
    days: dict[str, list[float]] = {}
    for d, _, t in rows:
        days.setdefault(d.at[:5], []).append(t)  # `at` — «ДД.ММ ЧЧ:ММ»
    n = s["scored"]
    sd, interval = ci95([t for _, _, t in rows])
    reason = (
        "сотрудник не указан"
        if name == UNKNOWN
        else f"недостаточно данных (n={n}, нужно ≥{MIN_SCORED})"
        if n < MIN_SCORED
        else None
    )
    return {
        "operator": name,
        "dialogs": s["dialogs"],
        "n": n,
        "avg_total": s["avg_total"],
        "sd": sd,
        "ci95": interval,
        "ranked": reason is None,
        "reason": reason,
        "gross_errors": s["risk"]["dialogs"],
        "needs_review": s["needs_review"],
        "appeals_open": s["open_appeals"],
        "weakest": [
            {"cid": c["id"], "name": c["name"], "share": c["share"]}
            for c in core["criteria"]
            if c["share"] < 1
        ][:3],
        # ponytail: года в `at` нет, на стыке декабря и января порядок дней ломается
        "trend": [
            {"day": day, "avg_total": r2(sum(ts) / len(ts)), "dialogs": len(ts)}
            for day, ts in sorted(days.items(), key=lambda kv: kv[0][3:5] + kv[0][:2])
        ],
        "dialog_ids": [d.id for d in mine],
        "reasons": core["reasons"],
    }


def _by_operator(dialogs: Sequence[Dialog]) -> dict[str, list[Dialog]]:
    groups: dict[str, list[Dialog]] = {}
    for d in dialogs:
        groups.setdefault(d.operator or UNKNOWN, []).append(d)
    return groups


def operators(
    checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]
) -> list[dict[str, Any]]:
    """GET /api/operators: строка на сотрудника в порядке `DEFINITIONS["order"]`."""
    rows = [
        {k: v for k, v in _operator(checklist, name, mine, appeals, {}).items() if k not in _CARD_ONLY}
        for name, mine in _by_operator(dialogs).items()
    ]
    return sorted(rows, key=lambda r: (not r["ranked"], r["avg_total"] if r["ranked"] else -r["n"]))


def operator_card(
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    owners: Mapping[str, str],
    name: str,
) -> dict[str, Any] | None:
    """GET /api/operators/{name}: строка списка, его диалоги и топ причин; неизвестное имя — None."""
    mine = _by_operator(dialogs).get(name)
    return _operator(checklist, name, mine, appeals, owners) if mine else None


def _section(checklist: Checklist, picked: Sequence[Dialog], appeals: Sequence[Appeal]) -> dict[str, Any]:
    """«По сотрудникам»: только ранжированные; до 5 «требуют внимания» (ниже средний итог) и до 3
    «сильные стороны» (выше), списки не пересекаются. Это не рейтинг: тех, у кого мало данных, тут нет."""
    rows = [r for r in operators(checklist, picked, appeals) if r["ranked"]]
    rows = rows if len(rows) >= 2 else []  # одного не с кем сравнить
    top = min(STRENGTHS, len(rows) // 2)
    return {"attention": rows[: min(ATTENTION, len(rows) - top)], "strengths": rows[::-1][:top]}


# --- Выводы словами ---


def _d(x: float | None, nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{round(100 * x)} %"


def _dialogs(k: int) -> str:
    if k % 10 == 1 and k % 100 != 11:
        return f"{k} диалог"
    return f"{k} диалога" if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14 else f"{k} диалогов"


def _of(n: int) -> str:
    """«из 1 диалога», «из 10 диалогов»."""
    return f"{n} диалога" if n % 10 == 1 and n % 100 != 11 else f"{n} диалогов"


def _findings(rep: dict[str, Any], resolution: bool) -> list[str]:
    s, n = rep["summary"], rep["summary"]["scored"]
    if not n:
        return []
    out = []
    if rep["criteria"] and (worst := rep["criteria"][0])["share"] < 1:
        out.append(
            f"Чаще всего баллы теряются на критерии „{worst['name']}“: средняя доля {_d(worst['share'])}."
        )
    risk = s["risk"]
    if risk["dialogs"]:
        kind = max(risk["kinds"], key=lambda k: k["n"])
        out.append(
            f"Грубые нарушения — в {risk['dialogs']} из {_of(n)} ({_pct(risk['share'])}), "
            f"чаще всего «{kind['label']}»: {kind['n']}."
        )
    elif risk["kinds"]:
        out.append("Грубых нарушений не найдено.")
    if resolution:
        nx = s["no_next_step"]
        out.append(
            f"Без решения или понятного следующего шага — {nx['dialogs']} из {_of(n)} ({_pct(nx['share'])})."
        )
    if rep["reasons"]:
        r = rep["reasons"][0]
        out.append(
            f"Самая частая причина потери баллов — «{r['tag']}»: {_dialogs(r['dialogs'])}, "
            f"что менять: {r['owner'].lower()}."
        )
    for title, groups in (("Языки", rep["langs"]), ("Каналы", rep["channels"])):
        lo, hi = min(groups, key=lambda g: g["avg"]), max(groups, key=lambda g: g["avg"])
        if lo["avg"] < hi["avg"]:
            out.append(
                f"{title}: ниже всего средний итог у «{lo['label']}» — {_d(lo['avg'])}, "
                f"выше всего у «{hi['label']}» — {_d(hi['avg'])}."
            )
            break
    return out[:5]


# --- Таблицы для html и md ---

Table = tuple[str, list[str], set[int], list[tuple[list[str], float]]]  # заголовок, шапка, числа, строки


OPERATOR_HEAD = [
    "Сотрудник",
    "Оценено (n)",
    "Средний итог",
    "95 % интервал",
    "Грубые нарушения",
    "Слабее всего",
]
NUM = {1, 2, 3, 4}  # числовые колонки OPERATOR_HEAD


def _tables(rep: dict[str, Any]) -> list[Table]:
    """Строки — (ячейки, доля для полоски 0..1). Пустые таблицы не выводятся."""
    risk = rep["summary"]["risk"]
    most = max((r["dialogs"] for r in rep["reasons"]), default=1)

    def groups(rows: list[dict[str, Any]]) -> list[tuple[list[str], float]]:
        return [([g["label"], str(g["n"]), _d(g["avg"])], g["avg"] / 100) for g in rows]

    def people(rows: list[dict[str, Any]]) -> list[tuple[list[str], float]]:
        return [
            (
                [
                    r["operator"],
                    str(r["n"]),
                    _d(r["avg_total"]),
                    f"{_d(r['ci95'][0])}–{_d(r['ci95'][1])}" if r["ci95"] else "—",
                    str(r["gross_errors"]),
                    ", ".join(w["name"] for w in r["weakest"]) or "—",
                ],
                r["avg_total"] / 100,
            )
            for r in rows
        ]

    tables: list[Table] = [
        (
            "Грубые нарушения по видам", ["Вид нарушения", "Диалогов"], {1},
            [([k["label"], str(k["n"])], k["n"] / (risk["dialogs"] or 1)) for k in risk["kinds"]],
        ),
        (
            "Результат по критериям", ["Критерий", "Применимо", "N/A", "Средняя доля баллов"], {1, 2, 3},
            [([c["name"], str(c["n"]), str(c["na"]), _d(c["share"])], c["share"]) for c in rep["criteria"]],
        ),
        (
            f"Причины потери баллов, топ-{TOP}", ["Причина", "Диалогов", "Что менять", "Критерии"], {1},
            [
                ([r["tag"], str(r["dialogs"]), r["owner"], ", ".join(r["criteria"])], r["dialogs"] / most)
                for r in rep["reasons"]
            ],
        ),
        ("По сотрудникам: требуют внимания", OPERATOR_HEAD, NUM, people(rep["operators"]["attention"])),
        ("По сотрудникам: сильные стороны", OPERATOR_HEAD, NUM, people(rep["operators"]["strengths"])),
        ("По каналам", ["Канал", "Диалогов", "Средний итог"], {1, 2}, groups(rep["channels"])),
        ("По языкам", ["Язык", "Диалогов", "Средний итог"], {1, 2}, groups(rep["langs"])),
    ]  # fmt: skip
    return [t for t in tables if t[3]]


def _scope(rep: dict[str, Any]) -> str:
    f = rep["filters"]
    parts = [
        f"язык {f['lang']}" if f["lang"] else "",
        f"канал: {CHANNEL[f['ch']].lower()}" if f["ch"] else "",
        f"сотрудник: {f['operator']}" if f.get("operator") else "",
    ]
    scope = ", ".join(p for p in parts if p)
    return f"Сформирован {rep['at']}" + (f" · {scope}" if scope else "")


def _short(s: dict[str, Any]) -> str:
    """Видимый счёт диалогов при неполных данных (docs/insufficient-data.md); нет таких — пусто."""
    parts = [f"недостаточно данных — {s['insufficient']}"] if s["insufficient"] else []
    parts += [f"мало данных — {s['low_data']}"] if s["low_data"] else []
    return "; " + ", ".join(parts) if parts else ""


def _tiles(rep: dict[str, Any]) -> list[tuple[str, str, str]]:
    s = rep["summary"]
    cost = s["cost"]
    return [
        (
            "Средний итог",
            _d(s["avg_total"]),
            f"из 100; оценено {s['scored']} из {_of(s['dialogs'])}{_short(s)}",
        ),
        ("Грубые нарушения", _pct(s["risk"]["share"]), _dialogs(s["risk"]["dialogs"])),
        ("Без следующего шага", _pct(s["no_next_step"]["share"]), _dialogs(s["no_next_step"]["dialogs"])),
        ("Нужна проверка", str(s["needs_review"]), "диалогов с расхождением моделей или без основания"),
        ("Апелляции", str(s["open_appeals"]), "на рассмотрении"),
        (
            "Стоимость оценки",
            "—" if cost["avg_usd"] is None else f"${_d(cost['avg_usd'], 4)}",
            "нет данных" if cost["avg_s"] is None else f"и {_d(cost['avg_s'], 1)} с на диалог",
        ),
    ]


# --- Markdown и CSV ---


def to_markdown(rep: dict[str, Any]) -> str:
    out = ["# Отчёт для руководства", "", _scope(rep), ""]
    if not rep["summary"]["scored"]:
        return "\n".join([*out, f"{EMPTY}.", ""])
    out += ["## Главное", "", *(f"- {f}" for f in rep["findings"]), ""]
    out += ["## Ключевые числа", "", *(f"- {k}: {v} — {note}" for k, v, note in _tiles(rep)), ""]
    for title, head, _, rows in _tables(rep):
        out += [f"## {title}", "", f"| {' | '.join(head)} |", "|" + " --- |" * len(head)]
        out += [f"| {' | '.join(map(md_cell, cells))} |" for cells, _ in rows]
        out.append("")
    return "\n".join([*out, NOTE, ""])


def to_csv(rep: dict[str, Any]) -> str:
    """Те же таблицы, что в html и md, для Excel; ключевые числа и выводы — первыми блоками."""
    tables = [
        Rows("Главное", ["Вывод"], [[f] for f in rep["findings"]]),
        Rows("Ключевые числа", ["Показатель", "Значение", "Пояснение"], [list(t) for t in _tiles(rep)]),
        *(Rows(t, head, [cells for cells, _ in rows]) for t, head, _, rows in _tables(rep)),
    ]
    return doc_csv(Doc("Отчёт для руководства", "Качество обслуживания", _scope(rep), tables, NOTE))


# --- Страница для печати ---

CSS = (
    TABLE_CSS
    + """
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 6px}
.tile{border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:8px;padding:8px 10px;
  break-inside:avoid}
.tile span{display:block;color:var(--muted);font-size:12px}
.tile b{display:block;font-size:22px;line-height:1.2}
.findings{margin:0;padding-left:20px}.findings li{margin:0 0 4px}
@media (max-width:640px){.tiles{grid-template-columns:1fr 1fr}}
"""
)


def _bar(x: float) -> str:
    """Полоска на SVG: в отличие от фона CSS печатается без настроек браузера."""
    w = round(120 * max(0.0, min(1.0, x)))
    return (
        '<svg width="120" height="10" aria-hidden="true">'
        '<rect width="120" height="10" rx="2" fill="#E2F1EB"/>'
        f'<rect width="{w}" height="10" rx="2" fill="#0E6A55"/></svg>'
    )


def _html_table(head: list[str], num: set[int], rows: list[tuple[list[str], float]]) -> str:
    cls = [' class="num"' if i in num else "" for i in range(len(head))]
    th = "".join(f"<th{c}>{escape(h)}</th>" for c, h in zip(cls, head, strict=True)) + "<th></th>"
    trs = "".join(
        "<tr>"
        + "".join(f"<td{c}>{escape(x)}</td>" for c, x in zip(cls, cells, strict=True))
        + f"<td>{_bar(v)}</td></tr>"
        for cells, v in rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def to_html(rep: dict[str, Any]) -> str:
    """Самодостаточная страница A4: стили внутри, внешних ссылок и скриптов нет, все данные экранированы."""
    if rep["summary"]["scored"]:
        tiles = "".join(
            f'<div class="tile"><span>{escape(k)}</span><b>{escape(v)}</b><span>{escape(note)}</span></div>'
            for k, v, note in _tiles(rep)
        )
        findings = "".join(f"<li>{escape(f)}</li>" for f in rep["findings"])
        body = (
            f'<h2>Главное</h2><ul class="findings">{findings}</ul>'
            f'<h2>Ключевые числа</h2><div class="tiles">{tiles}</div>'
            + "".join(
                f"<section><h2>{escape(t)}</h2>{_html_table(h, num, rows)}</section>"
                for t, h, num, rows in _tables(rep)
            )
            + f'<p class="note">{escape(NOTE)}</p>'
        )
    else:
        body = f'<p class="empty">{EMPTY}</p>'
    return page(
        "Отчёт для руководства", "Отчёт для руководства", "Качество обслуживания", _scope(rep), body, CSS
    )
