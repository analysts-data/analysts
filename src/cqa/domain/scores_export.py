"""Оценки для команды качества в Excel: строка на диалог (wide) или на оценённую пару диалог × критерий
(long). Чистые функции.

Ответ пары — с учётом последнего решения (`effective_answer`), итог — `scoring.total`: те же числа, что
видит интерфейс. Названия критериев и виды нарушений — из чек-листа.
"""

from collections.abc import Sequence
from typing import Literal

from cqa.domain.checklist_export import excel_csv
from cqa.domain.models import Answer, Appeal, Checklist, Criterion, Dialog
from cqa.domain.report import CHANNEL
from cqa.domain.review import awaits_review, effective_answer
from cqa.domain.scoring import frac, total

Shape = Literal["wide", "long"]
WIDE = [
    "ID", "Название", "Канал", "Язык", "Дата", "Итог", "Грубое нарушение", "Виды нарушений",
    "Нужна проверка", "Проверен",
]  # fmt: skip
LONG = [
    "ID диалога", "ID критерия", "Критерий", "Ответ", "Доля", "Обоснование", "Реплики-основания",
    "Причина", "Как сказать лучше", "Модель", "Решение проверяющего",
]  # fmt: skip
STATUS = {"confirmed": "Подтверждено", "changed": "Изменено"}


def answer_text(c: Criterion, a: Answer | None) -> str:
    """Как `ansTxt` в web/js/format.js."""
    if a is None:
        return "ждёт оценки"
    if isinstance(a, dict):
        return ", ".join(q.label for q in c.questions or [] if a.get(q.k)) or "Нарушений нет"
    if isinstance(a, int):
        return f"{a} из {max(c.steps or [a])}"
    return {"na": "N/A", "yes": "Да", "no": "Нет"}[a]


def _num(x: float | None) -> str:
    return "" if x is None else f"{x:.2f}".replace(".", ",")


def _yes(b: bool) -> str:
    return "да" if b else "нет"


def _decided(appeals: Sequence[Appeal], d: Dialog, cid: str) -> list[Appeal]:
    return [a for a in appeals if a.dlg == d.id and a.cid == cid and a.status in STATUS and a.to is not None]


def _decision(c: Criterion, decided: Sequence[Appeal]) -> str:
    if not decided:
        return ""
    x = decided[-1]
    what = answer_text(c, x.to)
    if x.status == "changed":
        what = f"{answer_text(c, x.from_)} → {what}"
    return " ".join(
        s for s in (f"{STATUS[x.status]}: {what}.", x.reason, x.reviewer and f"({x.reviewer})") if s
    )


def wide_rows(checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]) -> list[list[str]]:
    decided = {(a.dlg, a.cid) for a in appeals if a.status in STATUS}
    rows = [WIDE + [c.name for c in checklist.criteria]]
    for d in dialogs:
        answers = {cid: effective_answer(r, _decided(appeals, d, cid)) for cid, r in d.res.items()}
        kinds = [
            q.label
            for c in checklist.criteria
            if isinstance(a := answers.get(c.id), dict)
            for q in c.questions or []
            if a.get(q.k)
        ]
        rows.append([
            d.id, d.title or d.id, CHANNEL[d.ch], d.lang, d.at, _num(total(checklist, answers)),
            _yes(bool(kinds)), ", ".join(kinds), _yes(awaits_review(checklist.criteria, d, decided)),
            _yes(d.reviewed), *(answer_text(c, answers.get(c.id)) for c in checklist.criteria),
        ])  # fmt: skip
    return rows


def long_rows(checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]) -> list[list[str]]:
    rows = [LONG]
    for d in dialogs:
        for c in checklist.criteria:
            if (r := d.res.get(c.id)) is None:
                continue
            decided = _decided(appeals, d, c.id)
            a = effective_answer(r, decided)
            rows.append([
                d.id, c.id, c.name, answer_text(c, a), _num(frac(c, a)), r.why or "",
                ", ".join(map(str, r.ev)), r.tag or "", r.better or "", r.model or "", _decision(c, decided),
            ])  # fmt: skip
    return rows


def to_csv(
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    shape: Shape = "wide",
    *,
    lang: str | None = None,
    ch: str | None = None,
) -> str:
    """`dialogs` с текущими `res`, `appeals` — как в GET /api/state. Фильтры `lang`, `ch` необязательны."""
    lang = lang.upper() if lang else None
    picked = [d for d in dialogs if lang in (None, d.lang.upper()) and ch in (None, d.ch)]
    return excel_csv((wide_rows if shape == "wide" else long_rows)(checklist, picked, appeals))
