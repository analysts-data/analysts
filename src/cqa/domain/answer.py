"""Разбор и проверка ответа модели по одному критерию (design.md, п. 7–9)."""

import json
import re
from typing import Any

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```(?:json)?")
_KEYS = ("answer", "violation_found")


def parse_answer(text: str) -> dict[str, Any] | None:
    """Последний объект JSON с ключом ответа; рассуждение и ограждения пропускаются."""
    text = _FENCE.sub("", _THINK.sub("", text))
    decoder = json.JSONDecoder()
    found: dict[str, Any] | None = None
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            end = i + 1
        else:
            if isinstance(obj, dict) and any(k in obj for k in _KEYS):
                found = obj
        i = text.find("{", end)
    return found


def normalize(text: str) -> str:
    return " ".join(re.sub(r"\W", " ", text.casefold().replace("ё", "е")).split())
