"""Итог диалога: двойник `calc(...).total` из web/js/scoring.js (design/contract.md «Итог»)."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from cqa.domain.models import Answer, Checklist, Criterion


def r2(x: float) -> float:
    """Как `r2` в scoring.js: 12 значащих цифр снимают шум двоичной записи, затем половина вверх."""
    return float(Decimal(f"{x * 100:.12g}").quantize(Decimal(1), ROUND_HALF_UP)) / 100


def frac(c: Criterion, a: Answer) -> float | None:
    """Доля баллов, как `frac` в scoring.js: да 1, нет 0, шкала — ступень / максимум; N/A и флаг — None."""
    if a == "na" or c.type == "flag":
        return None
    if c.type == "bool":
        return 1.0 if a == "yes" else 0.0
    return a / max(c.steps or [a]) if isinstance(a, int) else None


def total(checklist: Checklist, answers: Mapping[str, Answer]) -> float | None:
    """100 × Σ(вес × доля) / Σ(вес применимых); N/A, флаги и критерии без ответа не входят."""
    w = g = 0.0
    for c in checklist.criteria:
        a = answers.get(c.id)
        f = None if a is None else frac(c, a)
        if f is None:
            continue
        w += c.w
        g += c.w * f
    return r2(100 * g / w) if w else None
