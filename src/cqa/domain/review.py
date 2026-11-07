"""Чистый домен проверки: допустимые ответы, отпечаток смысла, разница версий, решения, время."""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cqa.domain.models import Criterion

ASTANA = timezone(timedelta(hours=5))
Answer = str | int  # ответ критерия bool или scale; флаги не оспариваются


def allowed_answers(c: Criterion) -> list[Answer]:
    if c.type == "flag":
        return []
    base: list[Answer] = ["yes", "no"] if c.type == "bool" else list(c.steps or [])
    return base + ["na"] if c.na else base
