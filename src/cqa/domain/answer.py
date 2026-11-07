"""Разбор и проверка ответа модели по одному критерию (design.md, п. 7–9)."""

import json
import re
from collections.abc import Mapping
from typing import Any

from cqa.domain.models import Criterion, CriterionResult

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
    if isinstance(a, bool) or criterion.type == "flag":
        return None
    if criterion.type == "scale" and a != "na":
        try:
            step = float(a)
        except (TypeError, ValueError):
            return None
        a = int(step) if step.is_integer() else None
    return a if a is not None and criterion.accepts(a) else None


def _loses_points(a: str | int | None, criterion: Criterion) -> bool:
    return a == "no" or (isinstance(a, int) and a < max(criterion.steps or [0]))


def _exists(n: Any, lines: Mapping[int, str]) -> bool:
    return type(n) is int and n in lines


def _answer_error(raw: dict[str, Any], criterion: Criterion) -> str:
    if raw.get("answer") == "na":
        return "N/A для этого критерия не разрешён"
    na = ' или "na"' if criterion.na else ""
    if criterion.type == "scale":
        return f"answer — одно число из шкалы: {', '.join(map(str, criterion.steps or []))}{na}"
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
    if _loses_points(answer, criterion) and not ids and rng is None:
        errors.append("Для ответа с потерей баллов укажи реплику в turn_ids или участок в checked_range")
    return errors


def _seg(rng: Any) -> str | None:
    return f"реплики {rng[0]}–{rng[1]}" if rng else None


def to_result(
    raw: dict[str, Any], criterion: Criterion, *, ev_fail: bool, model: str, calls: int, cost: float, ms: int
) -> CriterionResult:
    """Проверенный ответ в CriterionResult; при ev_fail основание не подставляется."""
    a = allowed_answer(raw, criterion)
    lost = _loses_points(a, criterion)
    return CriterionResult(
        a=a,  # type: ignore[arg-type]
        ev=[] if ev_fail else raw.get("turn_ids") or [],
        seg=None if ev_fail else _seg(raw.get("checked_range")),
        why=raw.get("reason_ru"),
        quote=None if ev_fail else raw.get("quote") or None,
        tag=(raw.get("tag") or None) if lost else None,
        better=(raw.get("better") or None) if lost else None,
        evFail=ev_fail,
        model=model,
        calls=calls,
        cost=cost,
        ms=ms,
    )


def merge_flag(
    criterion: Criterion,
    subs: list[tuple[dict[str, Any] | None, bool]],
    *,
    model: str,
    calls: int,
    cost: float,
    ms: int,
) -> CriterionResult:
    """Флаг из подвопросов: (ответ или None, ev_fail) по порядку questions; None — «не найдено»."""
    questions = criterion.questions or []
    found = [
        (q, raw, fail)
        for q, (raw, fail) in zip(questions, subs, strict=True)
        if raw and raw.get("violation_found") is True
    ]
    keys = {q.k for q, _, _ in found}
    proven = [raw for _, raw, fail in found if not fail]
    why = [
        f"{q.label}: {raw.get('reason_ru') if raw else 'не найдено, модель не дала ответа'}"
        for q, (raw, _) in zip(questions, subs, strict=True)
    ]
    return CriterionResult(
        a={q.k: q.k in keys for q in questions},
        ev=sorted({n for raw in proven for n in raw["turn_ids"]}),
        seg=next((_seg(raw["checked_range"]) for raw in proven if raw.get("checked_range")), None),
        why="; ".join(why),
        quote=next((raw["quote"] for raw in proven), None),
        tag=", ".join(q.label for q, _, _ in found) or None,
        evFail=any(raw is None or fail for raw, fail in subs),
        model=model,
        calls=calls,
        cost=cost,
        ms=ms,
    )
