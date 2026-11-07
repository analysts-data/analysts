"""Локальное обезличивание диалога до отправки любой модели (design.md п. 18).

Шаблоны персональных данных применяются только вне квадратных скобок, поэтому
маски организаторов не меняются. Порядок замен: почта, IBAN, карта, ИИН,
телефон. Номера, роли, сегменты и время реплик не меняются, меняется только
текст реплик; входной диалог остаётся как есть.
"""

from __future__ import annotations

import re
from dataclasses import replace as _dataclass_replace
from typing import Any

# Порядок шаблонов — design.md п. 18: почта, IBAN KZ, карта 16 цифр, ИИН 12 цифр, телефон.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[ПОЧТА]"),
    (re.compile(r"(?<![A-Z0-9])KZ\d{2}[A-Z0-9]{16}(?![A-Z0-9])"), "[НОМЕР_СЧЁТА]"),
    (re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){3}(?!\d)"), "[НОМЕР_КАРТЫ]"),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[ДАННЫЕ_ИДЕНТИФИКАЦИИ]"),
    (re.compile(r"(?<!\d)(?:\+7|8)(?:[\s() -]*\d){10}(?!\d)"), "[ТЕЛЕФОН]"),
)

# Участки в квадратных скобках (маски организаторов) не перекрашиваем.
_OUTSIDE_BRACKETS = re.compile(r"[^\[\]]+")


def _apply_patterns(text: str) -> str:
    """Заменяет шаблоны только в участках вне квадратных скобок."""

    def substitute(match: re.Match[str]) -> str:
        segment = match.group(0)
        for pattern, label in _PATTERNS:
            segment = pattern.sub(label, segment)
        return segment

    return _OUTSIDE_BRACKETS.sub(substitute, text)


def _copy(obj: Any, **updates: Any) -> Any:
    """Новый объект pydantic или dataclass с обновлёнными полями."""
    model_copy = getattr(obj, "model_copy", None)
    if model_copy is not None:
        return model_copy(update=updates)
    return _dataclass_replace(obj, **updates)


def anonymize(dialog: Any) -> Any:
    """Новый диалог с обезличенным текстом реплик; вход не меняется."""
    lines = dialog.lines
    if lines is None:
        return _copy(dialog)
    new_lines = [
        _copy(line, text=_apply_patterns(line.text)) if getattr(line, "text", None) is not None else line
        for line in lines
    ]
    return _copy(dialog, lines=new_lines)
