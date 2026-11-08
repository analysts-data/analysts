"""История оценок диалога и возврат прежней оценки. Таблица results только растёт: возврат — копия строки."""

from typing import Any

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprints
from cqa.services.errors import Conflict, NotFound


def history(store: Store, dialog_id: str) -> dict[str, list[dict[str, Any]]]:
    """`GET /api/dialogs/{id}/history`: критерий → ответы, новые первыми. `current` — строка, которую
    считает итог; `stale` — ответ прежнему смыслу критерия (или критерию, которого нет в чек-листе)."""
    dialog = store.get_dialog(dialog_id)
    if dialog is None:
        raise NotFound(f"Диалог {dialog_id} не найден")
    checklist = store.current_checklist()
    assert checklist is not None, "create_app сеет чек-лист на пустой базе"
    fps = fingerprints(checklist)[dialog.ch]
    out: dict[str, list[dict[str, Any]]] = {}
    found: set[str] = set()  # критерии, чья текущая строка уже встретилась
    for row in reversed(store.result_rows(dialog_id=dialog_id)):
        stale = fps.get(row.cid) != row.fp
        current = not stale and row.cid not in found
        if current:
            found.add(row.cid)
        r = row.result
        out.setdefault(row.cid, []).append(
            {"id": row.id, "created": row.created, "run_id": row.run_id, "version": row.version,
             "model": r.model, "a": r.a, "why": r.why, "ev": r.ev, "current": current, "stale": stale}
        )  # fmt: skip
    return out


def restore(store: Store, result_id: int) -> CriterionResult:
    """`POST /api/results/{id}/restore`: копия строки становится последней и текущей."""
    row = store.get_result(result_id)
    if row is None:
        raise NotFound(f"Оценка {result_id} не найдена")
    dialog = store.get_dialog(row.dialog_id)
    checklist = store.current_checklist()
    assert dialog is not None and checklist is not None, "результат ссылается на диалог, чек-лист посеян"
    if fingerprints(checklist)[dialog.ch].get(row.cid) != row.fp:
        raise Conflict(
            f"Оценка {result_id} дана прежнему смыслу критерия {row.cid}: её нельзя сделать текущей"
        )
    pending = next(
        (
            a
            for a, _ in store.list_appeals()
            if (a.dlg, a.cid, a.status) == (row.dialog_id, row.cid, "pending")
        ),
        None,
    )
    if pending is not None:
        raise Conflict(f"По критерию {row.cid} есть апелляция на рассмотрении: {pending.id}")
    latest = max(
        r.id for r in store.result_rows(dialog_id=row.dialog_id) if (r.cid, r.fp) == (row.cid, row.fp)
    )
    if latest == row.id:
        raise Conflict(f"Оценка {result_id} уже текущая")
    store.add_result(row.dialog_id, row.cid, row.version, row.fp, row.result, run_id=row.run_id)
    return row.result
