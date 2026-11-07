"""Чистый домен проверки: допустимые ответы, отпечаток смысла, разница версий, решения, время."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cqa.domain.models import Appeal, Criterion, CriterionResult

ASTANA = timezone(timedelta(hours=5))
Answer = str | int  # ответ критерия bool или scale; флаги не оспариваются


def allowed_answers(c: Criterion) -> list[Answer]:
    if c.type == "flag":
        return []
    base: list[Answer] = ["yes", "no"] if c.type == "bool" else list(c.steps or [])
    return base + ["na"] if c.na else base


def effective_answer(result: CriterionResult, decided: Sequence[Appeal]) -> Answer:
    """`to` последнего решения пары (appeal или review, confirmed или changed), иначе ответ модели."""
    tos = [d.to for d in decided if d.status in ("confirmed", "changed") and d.to is not None]
    return tos[-1] if tos else result.a


def needs_review(c: Criterion, r: CriterionResult) -> bool:
    return c.type in ("bool", "scale") and (bool(r.evFail) or (r.alt is not None and r.alt != r.a))


def stamp(dt: datetime) -> str:
    return dt.astimezone(ASTANA).strftime("%d.%m %H:%M")
