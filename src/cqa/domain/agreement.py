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
    from collections.abc import Mapping

    from cqa.domain.models import Checklist, Criterion, CriterionResult, Dialog

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


# --- метрики одного прогона ---------------------------------------------------------------


@dataclass(frozen=True)
class Agreement:
    """Совпавших пар из учтённых (спорные не учтены)."""

    n: int
    ok: int

    @property
    def frac(self) -> float | None:
        return None if self.n == 0 else self.ok / self.n


@dataclass(frozen=True)
class Disagreement:
    dlg: str
    cid: str
    gold: list[Answer]
    got: Answer | None  # None — записи в res нет, критерий ждёт оценки
    why: str | None
    quote: str | None


@dataclass(frozen=True)
class GrossMetrics:
    """Грубые ошибки: полнота флага по подвопросам и языкам."""

    recall: dict[str, float | None]
    by_lang: dict[str, float | None]
    missed: list[tuple[str, str]]  # (dlg, подвопрос)
    false_flags: int
    positives_total: int
    found_total: int

    @property
    def overall(self) -> float | None:
        return None if self.positives_total == 0 else self.found_total / self.positives_total


@dataclass(frozen=True)
class RunMetrics:
    agree_total: Agreement
    per_lang: dict[str, Agreement]
    per_cid: dict[str, Agreement]
    missing: int
    gross: GrossMetrics
    disagreements: list[Disagreement]

    @property
    def kz_gap_pts(self) -> float | None:
        ru = self.per_lang.get("RU")
        kz = self.per_lang.get("KZ")
        if ru is None or kz is None or ru.frac is None or kz.frac is None:
            return None
        return round((ru.frac - kz.frac) * 100, 2)


def score_run(
    gold: list[GoldLabel],
    results: Mapping[str, Mapping[str, CriterionResult]],
    dialogs: Mapping[str, Dialog],
    checklist: Checklist,
) -> RunMetrics:
    """Совпадение с эталоном одного прогона: всего, по языкам и по критериям.

    Ответ совпал, если `a` входит в `ok` (для флага — равенство объекта).
    Спорные (`ok: null`) исключены; нет записи в `res` — несовпадение и `missing`.
    """
    flag_keys = {c.id: [q.k for q in c.questions or []] for c in checklist.criteria if c.type == "flag"}
    total = _Counter()
    per_lang: dict[str, _Counter] = {}
    per_cid: dict[str, _Counter] = {}
    missing = 0
    disagreements: list[Disagreement] = []
    pos_k: dict[str, int] = {k: 0 for keys in flag_keys.values() for k in keys}
    found_k: dict[str, int] = dict(pos_k)
    pos_lang: dict[str, int] = {}
    found_lang: dict[str, int] = {}
    missed: list[tuple[str, str]] = []
    false_flags = 0

    for label in gold:
        if label.ok is None:
            continue
        res = results.get(label.dlg, {}).get(label.cid)
        got = res.a if res is not None else None
        hit = got is not None and got in label.ok
        total.add(hit)
        lang = dialogs[label.dlg].lang if label.dlg in dialogs else None
        if lang is not None:
            per_lang.setdefault(lang, _Counter()).add(hit)
        per_cid.setdefault(label.cid, _Counter()).add(hit)
        if res is None:
            missing += 1
        if not hit:
            disagreements.append(
                Disagreement(
                    dlg=label.dlg,
                    cid=label.cid,
                    gold=list(label.ok),
                    got=got,
                    why=res.why if res is not None else None,
                    quote=res.quote if res is not None else None,
                )
            )
        keys = flag_keys.get(label.cid)
        if keys is not None:
            gold_true = {k for answer in label.ok if isinstance(answer, dict) for k, v in answer.items() if v}
            got_true = (
                {k for k, v in res.a.items() if v} if res is not None and isinstance(res.a, dict) else set()
            )
            for k in keys:
                if k in gold_true:
                    pos_k[k] += 1
                    if lang is not None:
                        pos_lang[lang] = pos_lang.get(lang, 0) + 1
                    if k in got_true:
                        found_k[k] += 1
                        if lang is not None:
                            found_lang[lang] = found_lang.get(lang, 0) + 1
                    else:
                        missed.append((label.dlg, k))
                if res is not None and k in got_true and k not in gold_true:
                    false_flags += 1

    gross = GrossMetrics(
        recall={k: (found_k[k] / pos_k[k] if pos_k[k] else None) for k in pos_k},
        by_lang={
            lang: (found_lang[lang] / pos_lang[lang] if pos_lang.get(lang) else None) for lang in pos_lang
        },
        missed=missed,
        false_flags=false_flags,
        positives_total=sum(pos_k.values()),
        found_total=sum(found_k.values()),
    )
    return RunMetrics(
        agree_total=total.agreement(),
        per_lang={lang: counter.agreement() for lang, counter in per_lang.items()},
        per_cid={cid: counter.agreement() for cid, counter in per_cid.items()},
        missing=missing,
        gross=gross,
        disagreements=disagreements,
    )


class _Counter:
    def __init__(self) -> None:
        self.n = 0
        self.ok = 0

    def add(self, hit: bool) -> None:
        self.n += 1
        self.ok += int(hit)

    def agreement(self) -> Agreement:
        return Agreement(n=self.n, ok=self.ok)


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
