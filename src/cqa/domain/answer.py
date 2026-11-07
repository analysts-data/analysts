"""Разбор и проверка ответа модели по одному критерию (design.md, п. 7–9)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cqa.domain.models import Criterion

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


def allowed_answer(raw: dict[str, Any], criterion: Criterion) -> str | int | None:
    """Ответ, разрешённый типом критерия; ступень шкалы приводится к int, иначе None."""
    a: Any = raw.get("answer")
    if a == "na":
        return "na" if criterion.na else None
    if criterion.type == "bool":
        return a if a in ("yes", "no") else None
    if criterion.type != "scale" or isinstance(a, bool):
        return None
    try:
        step = float(a)
    except (TypeError, ValueError):
        return None
    return int(step) if step.is_integer() and int(step) in criterion.steps else None


def _exists(n: Any, lines: Mapping[int, str]) -> bool:
    return type(n) is int and n in lines


def _answer_error(raw: dict[str, Any], criterion: Criterion) -> str:
    if raw.get("answer") == "na":
        return "N/A для этого критерия не разрешён"
    na = ' или "na"' if criterion.na else ""
    if criterion.type == "scale":
        return f"answer — одно число из шкалы: {', '.join(map(str, criterion.steps))}{na}"
    return f'answer — "yes" или "no"{na}'


def check(
    raw: dict[str, Any], criterion: Criterion, lines: Mapping[int, str], *, sub: bool = False
) -> list[str]:
    """Ошибки ответа по-русски; уходят модели при повторе. Пустой список — ответ принят."""
    errors: list[str] = []
    ids = raw.get("turn_ids") or []
    if not isinstance(ids, list):
        errors.append("turn_ids — список номеров реплик")
        ids = []
    quote = normalize(str(raw.get("quote") or ""))
    missing = [str(n) for n in ids if not _exists(n, lines)]
    if missing:
        errors.append(f"Нет реплик с номерами {', '.join(missing)}: укажи номера из диалога")
    if ids and not quote:
        errors.append("turn_ids указаны без quote: приведи дословную цитату из этих реплик")
    if quote and not ids:
        errors.append("quote указана без turn_ids: укажи номер реплики с этой цитатой")
    if quote and ids and not missing and not any(quote in normalize(lines[n]) for n in ids):
        errors.append(
            f"quote: цитата «{raw['quote']}» не найдена дословно в репликах {', '.join(map(str, ids))}"
        )
    rng = raw.get("checked_range")
    if rng is not None and not (
        isinstance(rng, list) and len(rng) == 2 and all(_exists(n, lines) for n in rng) and rng[0] <= rng[1]
    ):
        errors.append("checked_range — [от, до]: два номера реплик из диалога, от не больше до")
    if not str(raw.get("reason_ru") or "").strip():
        errors.append("reason_ru пуст: объясни ответ")
    if sub:
        found = raw.get("violation_found")
        if not isinstance(found, bool):
            errors.append("violation_found — true или false")
        elif found and not (ids and quote):
            errors.append("violation_found: true требует turn_ids и quote с репликой нарушения")
        return errors
    answer = allowed_answer(raw, criterion)
    if answer is None:
        errors.append(_answer_error(raw, criterion))
    lost = answer == "no" or (isinstance(answer, int) and answer < max(criterion.steps))
    if lost and not ids and rng is None:
        errors.append("Для ответа с потерей баллов укажи реплику в turn_ids или участок в checked_range")
    return errors
