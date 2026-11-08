"""Файл результатов «JSON 1.0» организаторов: чистое преобразование и проверка перед push.

Соответствие id критерия и кода организаторов — данные (`results/criteria_map.json`).
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from cqa.domain.models import Answer, Appeal, Checklist, Dialog
from cqa.domain.review import effective_answer
from cqa.domain.scoring import total

Value = bool | int | None


def _value(a: Answer) -> Value:
    """yes/no → true/false, na → null, ступень шкалы — число, флаг — true при любом нарушении."""
    if isinstance(a, dict):
        return any(a.values())
    if isinstance(a, int):
        return a
    return None if a == "na" else a == "yes"


def _error(conversation_id: str, reason: str) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "status": "error",
        "criteria": [],
        "score": None,
        "error": reason,
    }


def _record(
    conversation_id: str,
    dialog: Dialog | None,
    checklist: Checklist,
    appeals: Sequence[Appeal],
    codes: Mapping[str, str],
) -> dict[str, Any]:
    if dialog is None:
        return _error(conversation_id, "диалога нет в базе: запись источника не загружена")
    if (s := dialog.sufficiency) is not None and s.status == "block":  # не выдумывать итог: error с причиной
        why = "; ".join(f"{r.text} ({r.basis})" for r in s.reasons if r.outcome == "block")
        return _error(conversation_id, f"недостаточно данных: {why}")
    by_id = {c.id: c for c in checklist.criteria}
    pairs = {cid: [x for x in appeals if x.dlg == dialog.id and x.cid == cid] for cid in dialog.res}
    answers = {cid: effective_answer(r, pairs[cid]) for cid, r in dialog.res.items()}
    if missing := [cid for cid in codes if cid not in answers]:
        return _error(conversation_id, f"нет оценки по критериям {', '.join(missing)}")
    if bad := [cid for cid in codes if not by_id[cid].accepts(answers[cid])]:
        return _error(conversation_id, f"недопустимый ответ по критериям {', '.join(bad)}")
    criteria = []
    for cid, code in codes.items():
        r, a = dialog.res[cid], answers[cid]
        # ответ изменён решением: основание — причина решения, а не обоснование модели
        decided = next((x.reason for x in reversed(pairs[cid]) if x.to == a), None) if a != r.a else None
        criteria.append(
            {
                "criterion_id": code,
                "value": _value(a),
                "rationale": decided or r.why or "",
                "evidence_turns": list(r.ev),
            }
        )
    flags = [_value(answers[cid]) for cid in codes if by_id[cid].type == "flag"]
    return {
        "conversation_id": conversation_id,
        "status": "ok",
        "criteria": criteria,
        "score": {"final_score": total(checklist, answers), "critical_flag": any(flags)},
    }


def to_results(
    ids: Sequence[str],
    dialogs: Mapping[str, Dialog],
    checklist: Checklist,
    appeals: Sequence[Appeal],
    codes: Mapping[str, str],
    *,
    team: str,
    model: Mapping[str, str],
) -> dict[str, Any]:
    """Одна запись на каждый `conversation_id` набора в порядке источника; не оценённый — `error`.

    `dialogs` — с текущими `res`, `appeals` — решения для текущего смысла критериев (как в
    GET /api/state): итог считается с учётом последнего решения, как в интерфейсе.
    """
    known = {c.id for c in checklist.criteria}
    if missing := [cid for cid in codes if cid not in known]:
        raise ValueError(f"критериев {', '.join(missing)} из карты нет в текущем чек-листе")
    return {
        "schema_version": "1.0",
        "team_name": team,
        "model": dict(model),
        "results": [_record(i, dialogs.get(i), checklist, appeals, codes) for i in ids],
    }


def check_results(doc: Mapping[str, Any], codes: Iterable[str], expected: int | None = None) -> list[str]:
    """Проверка перед push: нет повторов id, у `ok` каждый код ровно один раз, число записей."""
    records = doc["results"]
    problems = [
        f"повтор conversation_id {i}: {n} записи"
        for i, n in Counter(r["conversation_id"] for r in records).items()
        if n > 1
    ]
    want = sorted(codes)
    for r in records:
        if r["status"] != "ok":
            continue
        got = sorted(c["criterion_id"] for c in r["criteria"])
        if got != want:
            problems.append(f"{r['conversation_id']}: коды {', '.join(got)}, нужны ровно {', '.join(want)}")
        if not isinstance(r["score"]["final_score"], int | float):
            problems.append(f"{r['conversation_id']}: final_score не число")
    if expected is not None and len(records) != expected:
        problems.append(f"записей {len(records)}, нужно ровно {expected}")
    return problems
