"""Ответ организаторов → `Dialog`: сегменты, свёртки, время."""

from collections.abc import Sequence
from typing import Literal

from cqa.domain.events import EventKind

Who = Literal["client", "operator", "bot", "system"]
Seg = Literal["pre", "conv", "internal", "after"]


def segments(who: Sequence[Who], kinds: Sequence[EventKind | None]) -> tuple[list[Seg], list[str]]:
    """Сегменты по порядку источника: `after` → `pre` → `internal` → `conv`; и предупреждения.

    Окно `internal` открыто, пока стоит флаг удержания или консультации; граничные события в окне.
    Первое `end` закрывает незакрытое окно и само остаётся `conv`.
    """
    if "operator" not in who:
        return ["pre"] * len(who), ["нет реплик оператора, все реплики pre"]
    first_op = list(who).index("operator")
    end = next((i for i, k in enumerate(kinds) if k == "end"), len(kinds))
    hold = consult = False
    segs: list[Seg] = []
    warnings: list[str] = []
    for i, k in enumerate(kinds):
        was_open = hold or consult
        if i == end and was_open:
            warnings.append(f"окно удержания или консультации не закрыто до реплики {i + 1}")
        if k == "hold_start":
            hold = True
        elif k == "hold_end":
            hold = False
        elif k == "consult_start":
            consult = True
        elif k == "consult_end":
            consult = False
        if i > end:
            segs.append("after")
        elif i < first_op:
            segs.append("pre")
        elif i < end and (was_open or hold or consult):
            segs.append("internal")
        else:
            segs.append("conv")
    if end == len(kinds) and (hold or consult):
        warnings.append("окно удержания или консультации не закрыто до конца диалога")
    return segs, warnings
