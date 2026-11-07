"""Итог диалога: двойник `calc(...).total` из web/js/scoring.js (design/contract.md «Итог»)."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from cqa.domain.models import Answer, Checklist


def r2(x: float) -> float:
    """Как `r2` в scoring.js: 12 значащих цифр снимают шум двоичной записи, затем половина вверх."""
    return float(Decimal(f"{x * 100:.12g}").quantize(Decimal(1), ROUND_HALF_UP)) / 100


def total(checklist: Checklist, answers: Mapping[str, Answer]) -> float | None:
    """100 × Σ(вес × доля) / Σ(вес применимых); N/A, флаги и критерии без ответа не входят."""
    w = g = 0.0
    for c in checklist.criteria:
        a = answers.get(c.id)
        if c.type == "flag" or a is None or a == "na":
            continue
        if c.type == "bool":
            f = 1.0 if a == "yes" else 0.0
        elif isinstance(a, int):
            f = a / max(c.steps or [a])
        else:
            continue
        w += c.w
        g += c.w * f
    return r2(100 * g / w) if w else None
