"""Соглашение с эталоном: чистый домен без ввода-вывода.

Форма строк эталона и определения метрик — изменение eval-and-delivery,
design-решения 1, 4 и 5. Чек-лист и результаты — структуры контракта
(design/contract.md), доступ только по полям.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cqa.domain.models import Checklist, Criterion

# "yes" | "no" | "na", ступень шкалы или объект подвопросов флага — форма поля `a`
Answer = Literal["yes", "no", "na"] | int | dict[str, bool]

By = Literal["team", "family", "adjudicated"]
BY_VALUES: tuple[str, ...] = ("team", "family", "adjudicated")


@dataclass(frozen=True)
class GoldLabel:
    dlg: str
    cid: str
    ok: tuple[Answer, ...] | None  # None — спорно, в счёт не идёт
    by: By
    note: str


def load_gold(lines: Iterable[str], checklist: Checklist) -> list[GoldLabel]:
    """Читает строки labels.jsonl, проверяет каждый ответ по чек-листу.

    Ошибки — ValueError с номером строки.
    """
    by_id = {c.id: c for c in checklist.criteria}
    seen: set[tuple[str, str]] = set()
    labels: list[GoldLabel] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        labels.append(_load_line(line, number, by_id, seen))
    return labels


def _load_line(line: str, number: int, by_id: dict[str, Criterion], seen: set[tuple[str, str]]):
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"строка {number}: не JSON: {exc.msg}") from exc
    if not isinstance(row, dict):
        raise ValueError(f"строка {number}: строка не является JSON-объектом")
    for field in ("dlg", "cid", "ok", "by"):
        if field not in row:
            raise ValueError(f"строка {number}: нет поля {field}")
    dlg, cid, by, note = row["dlg"], row["cid"], row["by"], row.get("note", "")

    def bad(reason: str) -> ValueError:
        return ValueError(f"строка {number} ({dlg}): {reason}")

    if not isinstance(dlg, str) or not dlg:
        raise bad("dlg должен быть непустой строкой")
    if not isinstance(cid, str):
        raise bad("cid должен быть строкой")
    if by not in BY_VALUES:
        raise bad(f"by должен быть одним из {BY_VALUES}, получен {by!r}")
    if by == "adjudicated" and not (isinstance(note, str) and note.strip()):
        raise bad("adjudicated требует непустую note с причиной решения")
    criterion = by_id.get(cid)
    if criterion is None:
        raise bad(f"неизвестный критерий {cid}")
    if (dlg, cid) in seen:
        raise bad(f"повтор пары {dlg}/{cid}")
    seen.add((dlg, cid))

    ok = row["ok"]
    if ok is None:
        return GoldLabel(dlg, cid, None, by, note)
    if not isinstance(ok, list) or not ok:
        raise bad("ok должен быть непустым списком или null")
    for answer in ok:
        _check_answer(answer, criterion, bad)
    return GoldLabel(dlg, cid, tuple(ok), by, note)


def _check_answer(answer: object, criterion: Criterion, bad) -> None:
    cid = criterion.id
    if criterion.type == "flag":
        keys = {q.k for q in criterion.questions or []}
        if not isinstance(answer, dict):
            raise bad(f"критерий {cid} (flag): ответ должен быть объектом подвопросов")
        if set(answer) != keys:
            extra = sorted(set(answer) - keys)
            missing = sorted(keys - set(answer))
            detail = f"лишние ключи {extra}" if extra else f"не хватает {missing}"
            raise bad(f"критерий {cid}: ключи подвопросов не совпадают с чек-листом, {detail}")
        if not all(isinstance(value, bool) for value in answer.values()):
            raise bad(f"критерий {cid}: значения подвопросов должны быть true или false")
        return
    if answer == "na":
        if not criterion.na:
            raise bad(f"критерий {cid} не допускает na")
        return
    if criterion.type == "bool":
        if answer not in ("yes", "no"):
            raise bad(f"критерий {cid} (bool): допустимы yes/no/na, получено {answer!r}")
        return
    if criterion.type == "scale":
        if isinstance(answer, bool) or not isinstance(answer, int):
            raise bad(f"критерий {cid} (scale): допустимы ступени {criterion.steps} или na")
        if answer not in (criterion.steps or []):
            raise bad(f"критерий {cid}: ступень {answer} вне шкалы {criterion.steps}")
        return
    raise bad(f"критерий {cid}: неизвестный тип {criterion.type}")
