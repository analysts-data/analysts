"""Чистый домен проверки: допустимые ответы, отпечаток смысла, разница версий, решения, время."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cqa.domain.models import Answer as ResultAnswer
from cqa.domain.models import Appeal, Checklist, Criterion, CriterionResult

ASTANA = timezone(timedelta(hours=5))
Answer = str | int  # ответ критерия bool или scale; флаги не оспариваются

# Поля смысла критерия: их смена требует новой оценки. name, w, sec, signal — лёгкие.
MEANING = {"text", "type", "steps", "stepText", "na", "naCond", "questions", "channel", "jev"}


def allowed_answers(c: Criterion) -> list[Answer]:
    if c.type == "flag":
        return []
    base: list[Answer] = ["yes", "no"] if c.type == "bool" else list(c.steps or [])
    return base + ["na"] if c.na else base


def fingerprint(checklist: Checklist, c: Criterion) -> str:
    meaning = c.model_dump(mode="json", include=MEANING)
    if c.jev is None:
        meaning.pop("jev", None)
    payload = [checklist.rules, meaning]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ChecklistDiff:
    pending: list[str]  # новые и изменённые по смыслу, порядок нового чек-листа
    light: list[str]  # изменены только name, w, sec или signal
    removed: list[str]  # порядок старого чек-листа
    rules: bool  # изменены общие правила
    changed: bool  # черновик отличается от текущей версии хоть чем-то, кроме version


def diff_checklists(old: Checklist, new: Checklist) -> ChecklistDiff:
    before = {c.id: c for c in old.criteria}
    after = {c.id for c in new.criteria}
    pending: list[str] = []
    light: list[str] = []
    for c in new.criteria:
        prev = before.get(c.id)
        if prev is None or fingerprint(old, prev) != fingerprint(new, c):
            pending.append(c.id)
        elif prev != c:
            light.append(c.id)
    return ChecklistDiff(
        pending=pending,
        light=light,
        removed=[c.id for c in old.criteria if c.id not in after],
        rules=old.rules != new.rules,
        changed=old.model_dump(exclude={"version"}) != new.model_dump(exclude={"version"}),
    )


def version_note(d: ChecklistDiff) -> str:
    parts = []
    if d.rules:
        parts.append("изменены общие правила")
    elif d.pending:
        parts.append("изменены " + ", ".join(d.pending))
    if d.light:
        parts.append("веса или названия " + ", ".join(d.light))
    if d.removed:
        parts.append("удалены " + ", ".join(d.removed))
    return "; ".join(parts) or "изменены секции"


def effective_answer(result: CriterionResult, decided: Sequence[Appeal]) -> ResultAnswer:
    """`to` последнего решения пары (appeal или review, confirmed или changed), иначе ответ модели."""
    tos = [d.to for d in decided if d.status in ("confirmed", "changed") and d.to is not None]
    return tos[-1] if tos else result.a


def needs_review(c: Criterion, r: CriterionResult) -> bool:
    return c.type in ("bool", "scale") and (r.evFail or (r.alt is not None and r.alt != r.a))


def stamp(dt: datetime) -> str:
    return dt.astimezone(ASTANA).strftime("%d.%m %H:%M")
