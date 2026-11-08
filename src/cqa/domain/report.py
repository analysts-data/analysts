"""Отчёт для руководства: ключевые числа, критерии, причины, каналы и языки, выводы. Чистые функции.

Ответ пары — с учётом последнего решения (`effective_answer`), итог — `scoring.total`, доля — `frac`:
те же числа, что видит интерфейс.
"""

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from cqa.domain.checklist_export import CSS as MEMO_CSS
from cqa.domain.models import Answer, Appeal, Checklist, Criterion, Dialog, Product
from cqa.domain.review import effective_answer, needs_review
from cqa.domain.scoring import frac, r2, total

TOP = 10
CHANNEL = {"chat": "Чат", "call": "Звонок"}
NOBODY = "Не назначено"
EMPTY = "Нет оценённых диалогов"
NO_TOPIC = "Тема не определена"
TOP_TOPIC = 3
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


def build_report(
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    owners: Mapping[str, str],
    *,
    at: str,
    lang: str | None = None,
    ch: str | None = None,
    products: Sequence[Product] = (),
) -> dict[str, Any]:
    """`dialogs` с текущими `res`, `appeals` — как в GET /api/state. Фильтры `lang`, `ch` необязательны.

    `products` — справочник тем: раздел «По продуктам» (`products`) только с ним.
    """
    lang = lang.upper() if lang else None
    picked = [d for d in dialogs if lang in (None, d.lang.upper()) and ch in (None, d.ch)]
    ids = {d.id for d in picked}
    appeals = [a for a in appeals if a.dlg in ids]
    decided = {(a.dlg, a.cid) for a in appeals if a.status in ("confirmed", "changed")}
    scored_cs = [c for c in checklist.criteria if c.type != "flag"]
    questions = [(fc.id, q) for fc in checklist.criteria if fc.type == "flag" for q in fc.questions or []]

    rows: list[tuple[Dialog, dict[str, Answer], float]] = []
    for d in picked:
        answers = {
            cid: effective_answer(r, [a for a in appeals if a.dlg == d.id and a.cid == cid])
            for cid, r in d.res.items()
        }
        if (t := total(checklist, answers)) is not None:
            rows.append((d, answers, t))
    n = len(rows)

    def found(answers: dict[str, Answer], cid: str, k: str) -> bool:
        a = answers.get(cid)
        return isinstance(a, dict) and bool(a.get(k))

    flagged = sum(any(found(ans, cid, q.k) for cid, q in questions) for _, ans, _ in rows)
    no_next = sum(
        any(c.signal == "resolution" and _lost(c, ans.get(c.id)) for c in scored_cs) for _, ans, _ in rows
    )
    review = sum(
        not d.reviewed
        and any(
            (r := d.res.get(c.id)) is not None and needs_review(c, r) and (d.id, c.id) not in decided
            for c in scored_cs
        )
        for d, _, _ in rows
    )
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

    rep: dict[str, Any] = {
        "at": at,
        "filters": {"lang": lang, "ch": ch},
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
    if products:
        stats = product_stats(checklist, picked, appeals, owners, products)
        rep["products"] = sorted((p for p in stats if p["dialogs"]), key=lambda p: -p["dialogs"])
    rep["findings"] = _findings(rep, any(c.signal == "resolution" for c in scored_cs))
    return rep


def product_stats(
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    owners: Mapping[str, str],
    products: Sequence[Product],
) -> list[dict[str, Any]]:
    """`GET /api/products/stats`: по каждой теме справочника и «Тема не определена» (тема не выбрана, ошибка,
    тема удалена из справочника) — те же числа, что в отчёте на этих диалогах."""
    known = {p.id for p in products}

    def topic(d: Dialog) -> str | None:
        pid = d.product.id if d.product and d.product.status == "done" else None
        return pid if pid in known else None

    groups: list[tuple[str | None, str]] = [(p.id, p.name) for p in products]
    if any(topic(d) is None for d in dialogs):
        groups.append((None, NO_TOPIC))
    out = []
    for pid, name in groups:
        subset = [d for d in dialogs if topic(d) == pid]
        rep = build_report(checklist, subset, appeals, owners, at="")
        s = rep["summary"]
        out.append(
            {
                "id": pid,
                "name": name,
                "dialogs": s["dialogs"],
                "scored": s["scored"],
                "avg_total": s["avg_total"],
                "risk_share": s["risk"]["share"],
                "no_next_step_share": s["no_next_step"]["share"],
                "needs_review": sum(bool(d.product and d.product.needs_review) for d in subset),
                "reasons": [
                    {k: r[k] for k in ("tag", "dialogs", "owner")} for r in rep["reasons"][:TOP_TOPIC]
                ],
                "weakest": [
                    {k: c[k] for k in ("id", "name", "share")}
                    for c in rep["criteria"][:TOP_TOPIC]
                    if c["share"] < 1
                ],
            }
        )
    return out


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
    scored_topics = [p for p in rep.get("products", []) if p["avg_total"] is not None and p["id"]]
    if len(scored_topics) > 1:
        lo = min(scored_topics, key=lambda p: p["avg_total"])
        hi = max(scored_topics, key=lambda p: p["avg_total"])
        if lo["avg_total"] < hi["avg_total"]:
            out.append(
                f"Темы: ниже всего средний итог у «{lo['name']}» — {_d(lo['avg_total'])}, "
                f"выше всего у «{hi['name']}» — {_d(hi['avg_total'])}."
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


def _tables(rep: dict[str, Any]) -> list[Table]:
    """Строки — (ячейки, доля для полоски 0..1). Пустые таблицы не выводятся."""
    risk = rep["summary"]["risk"]
    most = max((r["dialogs"] for r in rep["reasons"]), default=1)

    def groups(rows: list[dict[str, Any]]) -> list[tuple[list[str], float]]:
        return [([g["label"], str(g["n"]), _d(g["avg"])], g["avg"] / 100) for g in rows]

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
        (
            "По продуктам",
            ["Тема", "Диалогов", "Средний итог", "Грубые нарушения", "Без след. шага", "Главная причина"],
            {1, 2, 3, 4},
            [
                (
                    [
                        p["name"], str(p["dialogs"]), _d(p["avg_total"]), _pct(p["risk_share"]),
                        _pct(p["no_next_step_share"]), p["reasons"][0]["tag"] if p["reasons"] else "—",
                    ],
                    (p["avg_total"] or 0) / 100,
                )
                for p in rep.get("products", [])
            ],
        ),
        ("По каналам", ["Канал", "Диалогов", "Средний итог"], {1, 2}, groups(rep["channels"])),
        ("По языкам", ["Язык", "Диалогов", "Средний итог"], {1, 2}, groups(rep["langs"])),
    ]  # fmt: skip
    return [t for t in tables if t[3]]


def _scope(rep: dict[str, Any]) -> str:
    f = rep["filters"]
    parts = [
        f"язык {f['lang']}" if f["lang"] else "",
        f"канал: {CHANNEL[f['ch']].lower()}" if f["ch"] else "",
    ]
    scope = ", ".join(p for p in parts if p)
    return f"Сформирован {rep['at']}" + (f" · {scope}" if scope else "")


def _tiles(rep: dict[str, Any]) -> list[tuple[str, str, str]]:
    s = rep["summary"]
    cost = s["cost"]
    return [
        ("Средний итог", _d(s["avg_total"]), f"из 100; оценено {s['scored']} из {_of(s['dialogs'])}"),
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


# --- Markdown ---


def _md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def to_markdown(rep: dict[str, Any]) -> str:
    out = ["# Отчёт для руководства", "", _scope(rep), ""]
    if not rep["summary"]["scored"]:
        return "\n".join([*out, f"{EMPTY}.", ""])
    out += ["## Главное", "", *(f"- {f}" for f in rep["findings"]), ""]
    out += ["## Ключевые числа", "", *(f"- {k}: {v} — {note}" for k, v, note in _tiles(rep)), ""]
    for title, head, _, rows in _tables(rep):
        out += [f"## {title}", "", f"| {' | '.join(head)} |", "|" + " --- |" * len(head)]
        out += [f"| {' | '.join(_md(c) for c in cells)} |" for cells, _ in rows]
        out.append("")
    return "\n".join([*out, NOTE, ""])


# --- Страница для печати ---

CSS = (
    MEMO_CSS
    + """
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 6px}
.tile{border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:8px;padding:8px 10px;
  break-inside:avoid}
.tile span{display:block;color:var(--muted);font-size:12px}
.tile b{display:block;font-size:22px;line-height:1.2}
.findings{margin:0;padding-left:20px}.findings li{margin:0 0 4px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--muted);font-weight:600;font-size:12px}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
tr{break-inside:avoid}
.empty{font-size:18px;color:var(--muted);text-align:center;padding:40px 0}
@media (max-width:640px){main{padding:16px}.tiles{grid-template-columns:1fr 1fr}}
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
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Отчёт для руководства</title><style>{CSS}</style></head><body><main>"
        '<header><div><p class="kicker">Отчёт для руководства</p><h1>Качество обслуживания</h1>'
        f'<p class="meta">{escape(_scope(rep))}</p></div>'
        '<button type="button" class="noprint" onclick="window.print()">Печать / PDF</button></header>'
        f"{body}</main></body></html>"
    )
