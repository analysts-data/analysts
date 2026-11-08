"""Чек-лист для людей: CSV для Excel, Markdown, памятка для печати и разница версий. Чистые функции."""

import csv
import io
import json
from html import escape
from typing import Any

from cqa.domain.models import Checklist, Criterion
from cqa.domain.review import MEANING

TYPE = {"bool": "Да / Нет", "scale": "Шкала", "flag": "Флаг нарушения, без баллов"}
CHANNEL = {"all": "все каналы", "chat": "чат", "call": "звонок"}
SIGNAL = {"resolution": "решение запроса", "risk": "риск"}
FIELD = {
    "sec": "раздел", "name": "название", "type": "тип", "w": "вес", "na": "N/A", "naCond": "условие N/A",
    "signal": "сигнал", "steps": "ступени", "stepText": "тексты ступеней", "questions": "вопросы флага",
    "text": "текст", "call": "уточнение для звонка", "channel": "канал", "jev": "вопрос Jev",
}  # fmt: skip
# долю с N/A заранее не узнать: вес неприменимого критерия делится между остальными на каждом диалоге
SHARE = "при всех применимых"
HEADER = [
    "ID", "Раздел", "Название", "Тип", "Вес", f"Доля в итоге, % ({SHARE})", "N/A", "Условие N/A", "Канал",
    "Что проверяем", "Ступени шкалы", "Уточнение для звонка", "Вопросы флага",
]  # fmt: skip


def _num(x: float) -> str:
    return f"{round(x, 1):g}".replace(".", ",")


def _section(cl: Checklist, sec: int) -> str:
    return cl.sections[sec] if 0 <= sec < len(cl.sections) else str(sec)


def shares_of(cl: Checklist) -> dict[str, float]:
    """Доля веса оценочного критерия в итоге, %, если применимы все. Флаг баллов не даёт."""
    scored = [c for c in cl.criteria if c.type != "flag"]
    total = sum(c.w for c in scored)
    return {c.id: 100 * c.w / total if total else 0.0 for c in scored}


def _steps(c: Criterion) -> list[tuple[str, str]]:
    return [(str(s), (c.stepText or {}).get(str(s), "")) for s in c.steps or []] if c.type == "scale" else []


def _questions(c: Criterion) -> list[str]:
    qs = (c.questions or []) if c.type == "flag" else []
    return [q.label + (f" — {q.text}" if q.text else "") for q in qs]


def _weight(c: Criterion, shares: dict[str, float]) -> str:
    return f"вес {_num(c.w)}, доля в итоге {_num(shares[c.id])} % ({SHARE})" if c.id in shares else ""


def _na(c: Criterion) -> str:
    return f"N/A разрешён: {c.naCond or 'условие не указано'}" if c.na else "N/A не разрешён"


# --- CSV для Excel ---


def _cell(s: str) -> str:
    """Ячейка с = + - @ в начале — формула для Excel: апостроф оставляет её текстом."""
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(cl: Checklist) -> str:
    """UTF-8 с BOM и «;»: русский Excel открывает файл сразу. Строка на критерий, правил нет."""
    shares = shares_of(cl)
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";")
    out.writerow(HEADER)
    for c in cl.criteria:
        row = [
            c.id, _section(cl, c.sec), c.name, TYPE[c.type],
            _num(c.w) if c.id in shares else "", _num(shares[c.id]) if c.id in shares else "",
            "да" if c.na else "нет", (c.naCond or "") if c.na else "", CHANNEL[c.channel], c.text,
            "; ".join(f"{s} — {t}" for s, t in _steps(c)), c.call or "", "; ".join(_questions(c)),
        ]  # fmt: skip
        out.writerow([_cell(x) for x in row])
    return "﻿" + buf.getvalue()


# --- Markdown ---


def to_markdown(cl: Checklist) -> str:
    shares = shares_of(cl)
    total = sum(c.w for c in cl.criteria if c.id in shares)
    out = [f"# Чек-лист v{cl.version}", "", "## Общие правила", "", cl.rules.strip() or "—", ""]
    out += [
        f"Сумма весов {_num(total)}, итог приводится к 100. Доля в итоге указана {SHARE} критериях: "
        "вес неприменимого (N/A) критерия делится между остальными.",
        "",
    ]
    for si, sec in enumerate(cl.sections):
        out += [f"## {si + 1}. {sec}", ""]
        for c in (c for c in cl.criteria if c.sec == si):
            meta = " · ".join(
                x for x in (TYPE[c.type], _weight(c, shares), f"канал: {CHANNEL[c.channel]}") if x
            )
            out += [f"### {c.id}. {c.name}", "", meta, "", c.text, ""]
            if steps := _steps(c):
                out += ["Ступени:", *(f"- {s} — {t}" for s, t in steps), ""]
            if qs := _questions(c):
                out += ["Вопросы флага:", *(f"- {q}" for q in qs), ""]
            if c.type != "flag":
                out += [_na(c), ""]
            if c.call:
                out += [f"На звонке: {c.call}", ""]
    return "\n".join(out)


# --- Памятка для печати ---

CSS = """
:root{--accent:#0E6A55;--accent-soft:#E2F1EB;--ink:#17201C;--muted:#56635D;--line:#E0E6E3}
*{box-sizing:border-box}
body{margin:0;background:#F3F5F4;color:var(--ink);
  font:14px/1.5 "Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif}
main{max-width:210mm;margin:24px auto;background:#fff;padding:18mm 16mm;border-radius:10px;
  box-shadow:0 1px 2px rgba(23,32,28,.05)}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
  border-bottom:3px solid var(--accent);padding-bottom:10px;margin-bottom:16px}
.kicker{margin:0;color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.06em;font-size:12px}
h1{margin:2px 0 0;font-size:24px}
h2{font-size:16px;color:var(--accent);margin:22px 0 8px;border-bottom:1px solid var(--line);
  padding-bottom:4px}
h3{font-size:14px;margin:0 0 4px;display:flex;gap:8px;align-items:baseline}
.id{color:var(--muted);font-weight:600}
.meta,.note{color:var(--muted);font-size:12px;margin:0 0 6px}
.rules,.text{white-space:pre-line;margin:0 0 6px}
.crit{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:10px 12px;
  margin:0 0 10px;break-inside:avoid}
.crit ul{margin:4px 0 6px;padding-left:20px}
.na{background:var(--accent-soft);border-radius:6px;padding:4px 8px;font-size:13px;margin:6px 0 0}
.call{font-size:13px;margin:6px 0 0}
button{font:inherit;font-weight:600;color:#fff;background:var(--accent);border:0;border-radius:8px;
  padding:9px 14px;cursor:pointer}
@page{size:A4;margin:14mm}
@media print{body{background:#fff}main{margin:0;padding:0;box-shadow:none;max-width:none}
  .noprint{display:none}}
"""


def _html_criterion(c: Criterion, shares: dict[str, float]) -> str:
    e = escape
    meta = " · ".join(x for x in (TYPE[c.type], _weight(c, shares), f"канал: {CHANNEL[c.channel]}") if x)
    parts = [
        f'<article class="crit"><h3><span class="id">{e(c.id)}</span>{e(c.name)}</h3>',
        f'<p class="meta">{e(meta)}</p><p class="text">{e(c.text)}</p>',
    ]
    if steps := _steps(c):
        parts.append("<ul>" + "".join(f"<li><b>{e(s)}</b> — {e(t)}</li>" for s, t in steps) + "</ul>")
    if qs := _questions(c):
        parts.append("<ul>" + "".join(f"<li>{e(q)}</li>" for q in qs) + "</ul>")
    if c.type != "flag":
        parts.append(f'<p class="na">{e(_na(c))}</p>')
    if c.call:
        parts.append(f'<p class="call"><b>На звонке:</b> {e(c.call)}</p>')
    return "".join(parts) + "</article>"


def to_html(cl: Checklist) -> str:
    """Самодостаточная страница A4: стили внутри, внешних ссылок нет, весь текст экранирован."""
    shares = shares_of(cl)
    sections = "".join(
        f"<section><h2>{si + 1}. {escape(sec)}</h2>"
        + "".join(_html_criterion(c, shares) for c in cl.criteria if c.sec == si)
        + "</section>"
        for si, sec in enumerate(cl.sections)
    )
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Памятка оператора — чек-лист v{cl.version}</title><style>{CSS}</style></head><body><main>"
        f'<header><div><p class="kicker">Памятка оператора</p><h1>Чек-лист v{cl.version}</h1></div>'
        '<button type="button" class="noprint" onclick="window.print()">Печать / PDF</button></header>'
        f'<h2>Общие правила</h2><p class="rules">{escape(cl.rules)}</p>'
        f'<p class="note">Доля в итоге указана {SHARE} критериях: вес неприменимого (N/A) критерия '
        "делится между остальными.</p>"
        f"{sections}</main></body></html>"
    )


# --- Разница версий ---

REEVALUATE = MEANING | {"call"}  # call — смысл только для звонков, чаты не пересчитываются


def diff(old: Checklist, new: Checklist) -> dict[str, Any]:
    """Что изменилось от old к new. `reevaluate` — смена смысла критерия (для call — только звонков);
    вес, название, раздел и сигнал пересчитывают итог без модели. Раздел сравнивается по названию.
    При `rules_changed` заново оценивается весь чек-лист."""
    before = {c.id: c for c in old.criteria}
    after = {c.id for c in new.criteria}
    changed = []
    for c in new.criteria:
        if (prev := before.get(c.id)) is None:
            continue
        x, y = prev.model_dump(mode="json"), c.model_dump(mode="json")
        x["sec"], y["sec"] = _section(old, prev.sec), _section(new, c.sec)
        fields = [{"field": k, "from": x[k], "to": y[k]} for k in x if k != "id" and x[k] != y[k]]
        if fields:
            changed.append(
                {"id": c.id, "reevaluate": any(f["field"] in REEVALUATE for f in fields), "fields": fields}
            )
    return {
        "rules_changed": old.rules != new.rules,
        "added": [{"id": c.id, "name": c.name} for c in new.criteria if c.id not in before],
        "removed": [{"id": c.id, "name": c.name} for c in old.criteria if c.id not in after],
        "changed": changed,
    }


def _value(field: str, v: Any) -> str:
    if v is None or v == "" or v == []:
        return "—"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if field in ("type", "channel", "signal"):
        return {**TYPE, **CHANNEL, **SIGNAL}.get(v, str(v))
    if field == "w":
        return _num(v)
    if field == "steps":
        return ", ".join(map(str, v))
    if field == "stepText":
        return "; ".join(f"{k} — {t}" for k, t in v.items())
    if field == "questions":
        return "; ".join(q["label"] for q in v)
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


QUOTED = {"sec", "name", "text", "naCond", "call", "stepText", "questions"}


def _change(f: dict[str, Any]) -> str:
    a, b = _value(f["field"], f["from"]), _value(f["field"], f["to"])
    if f["field"] in QUOTED:
        a, b = (s if s == "—" else f"«{s}»" for s in (a, b))
    return f"- {FIELD.get(f['field'], f['field'])}: {a} → {b}"


def _verdict(fields: list[dict[str, Any]]) -> str:
    names = {f["field"] for f in fields}
    if names & MEANING:
        return "Нужна новая оценка по всем диалогам."
    if "call" in names:
        return "Нужна новая оценка только звонков: уточнение для звонка чаты не меняет."
    return "Новая оценка не нужна: итоги пересчитаются сразу."


def diff_markdown(old: Checklist, new: Checklist) -> str:
    d = diff(old, new)
    out = [f"# Что изменится: v{old.version} → v{new.version}", ""]
    if (
        not (d["rules_changed"] or d["added"] or d["removed"] or d["changed"])
        and old.sections == new.sections
    ):
        return "\n".join([*out, "Изменений нет.", ""])
    if d["rules_changed"]:
        out += [
            "## Общие правила изменены", "",
            "Правила входят в смысл каждого критерия: после сохранения весь чек-лист оценивается заново.", "",
            "Было:", "", old.rules, "", "Стало:", "", new.rules, "",
        ]  # fmt: skip
    if old.sections != new.sections:
        out += [
            "## Разделы",
            "",
            f"- было: {', '.join(old.sections)}",
            f"- стало: {', '.join(new.sections)}",
            "",
        ]
    if d["added"]:
        out += ["## Добавлены", "", *(f"- {a['id']} «{a['name']}» — нужна оценка" for a in d["added"]), ""]
    if d["removed"]:
        out += ["## Удалены", "", *(f"- {r['id']} «{r['name']}»" for r in d["removed"]), ""]
    if d["changed"]:
        names = {c.id: c.name for c in new.criteria}
        out += ["## Изменены", ""]
        for ch in d["changed"]:
            out += [f"### {ch['id']} «{names[ch['id']]}»", "", _verdict(ch["fields"]), ""]
            out += [*map(_change, ch["fields"]), ""]
    calls_only = {c["id"] for c in d["changed"] if not {f["field"] for f in c["fields"]} & MEANING}
    again = (
        [c.id for c in new.criteria]
        if d["rules_changed"]
        else [a["id"] for a in d["added"]]
        + [
            c["id"] + (" (только звонки)" if c["id"] in calls_only else "")
            for c in d["changed"]
            if c["reevaluate"]
        ]
    )
    out += ["## Итог", ""]
    out.append(
        f"Ждут новой оценки после сохранения: {', '.join(again)}." if again else "Новая оценка не нужна."
    )
    if again or d["removed"]:
        out.append("Ожидающие апелляции по удалённым и изменённым по смыслу критериям закрываются.")
    return "\n".join([*out, ""])
