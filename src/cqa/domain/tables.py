"""Общая форма отчёта — заголовок и таблицы строк — и её csv, md и html. Чистые функции.

json отчёта — его данные как есть; эта форма — для людей: Excel, вики и почта, печать.
"""

from dataclasses import dataclass
from html import escape

from cqa.domain.checklist_export import CSS as MEMO_CSS
from cqa.domain.checklist_export import excel_csv

EMPTY = "Нет данных"


@dataclass(frozen=True)
class Table:
    title: str
    head: list[str]
    rows: list[list[str]]
    num: frozenset[int] | set[int] = frozenset()  # колонки с числами: в html по правому краю


@dataclass(frozen=True)
class Doc:
    kicker: str
    title: str
    meta: str
    tables: list[Table]
    note: str = ""


def _shown(doc: Doc) -> list[Table]:
    return [t for t in doc.tables if t.rows]


def to_csv(doc: Doc) -> str:
    """UTF-8 с BOM и «;» (`excel_csv`) для русского Excel; таблицы — блоками через пустую строку."""
    rows: list[list[str]] = [[doc.title], [doc.meta]]
    for t in _shown(doc):
        rows += [[], [t.title], t.head, *t.rows]
    return excel_csv(rows)


def md_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def to_markdown(doc: Doc) -> str:
    out = [f"# {doc.title}", "", doc.meta, ""]
    for t in _shown(doc):
        out += [f"## {t.title}", "", f"| {' | '.join(map(md_cell, t.head))} |", "|" + " --- |" * len(t.head)]
        out += [f"| {' | '.join(map(md_cell, row))} |" for row in t.rows]
        out.append("")
    if not _shown(doc):
        out += [f"{EMPTY}.", ""]
    return "\n".join([*out, doc.note, ""] if doc.note else out)


CSS = (
    MEMO_CSS
    + """
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--muted);font-weight:600;font-size:12px}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
tr{break-inside:avoid}
.empty{font-size:18px;color:var(--muted);text-align:center;padding:40px 0}
@media (max-width:640px){main{padding:16px}}
"""
)


def page(title: str, kicker: str, h1: str, meta: str, body: str, css: str = CSS) -> str:
    """Самодостаточная страница A4: стили внутри, внешних ссылок и скриптов нет. body уже экранирован."""
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{css}</style></head><body><main>"
        f'<header><div><p class="kicker">{escape(kicker)}</p><h1>{escape(h1)}</h1>'
        f'<p class="meta">{escape(meta)}</p></div>'
        '<button type="button" class="noprint" onclick="window.print()">Печать / PDF</button></header>'
        f"{body}</main></body></html>"
    )


def _html_table(t: Table) -> str:
    cls = [' class="num"' if i in t.num else "" for i in range(len(t.head))]
    th = "".join(f"<th{c}>{escape(h)}</th>" for c, h in zip(cls, t.head, strict=True))
    trs = "".join(
        "<tr>" + "".join(f"<td{c}>{escape(x)}</td>" for c, x in zip(cls, row, strict=True)) + "</tr>"
        for row in t.rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def to_html(doc: Doc) -> str:
    body = "".join(f"<section><h2>{escape(t.title)}</h2>{_html_table(t)}</section>" for t in _shown(doc))
    body = body or f'<p class="empty">{EMPTY}</p>'
    if doc.note:
        body += f'<p class="note">{escape(doc.note)}</p>'
    return page(f"{doc.kicker}: {doc.title}", doc.kicker, doc.title, doc.meta, body)
