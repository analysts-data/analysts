"""История оценок диалога и возврат прежней оценки. Таблица results только растёт: возврат — копия строки."""

from typing import Any

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprints
from cqa.services.errors import Conflict, NotFound
from cqa.services.runs import held_by_human


def history(store: Store, dialog_id: str) -> dict[str, list[dict[str, Any]]]:
    """`GET /api/dialogs/{id}/history`: критерий → ответы, новые первыми. `current` — строка, которую
    считает итог; `stale` — ответ прежнему смыслу критерия (или критерию, которого нет в чек-листе)."""
    dialog = store.get_dialog(dialog_id)
    if dialog is None:
        raise NotFound(f"Диалог {dialog_id} не найден")
    checklist = store.current_checklist()
    assert checklist is not None, "create_app сеет чек-лист на пустой базе"
    fps = fingerprints(checklist)[dialog.ch]
    rows = store.result_rows(dialog_id=dialog_id)
    overrides = {i: run.override for i in {r.run_id for r in rows if r.run_id} if (run := store.get_run(i))}
    out: dict[str, list[dict[str, Any]]] = {}
    found: set[str] = set()  # критерии, чья текущая строка уже встретилась
    for row in reversed(rows):
        stale = fps.get(row.cid) != row.fp
        current = not stale and not row.shadow and row.cid not in found
        if current:
            found.add(row.cid)
        r = row.result
        out.setdefault(row.cid, []).append(
            {"id": row.id, "created": row.created, "run_id": row.run_id, "version": row.version,
             "model": r.model, "a": r.a, "why": r.why, "ev": r.ev, "current": current, "stale": stale,
             "shadow": row.shadow, "override": overrides.get(row.run_id) if row.run_id else None}
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
    same = [
        r.id
        for r in store.result_rows(dialog_id=row.dialog_id)
        if (r.cid, r.fp, r.shadow) == (row.cid, row.fp, False)
    ]
    if not row.shadow and row.id == max(same):
        raise Conflict(f"Оценка {result_id} уже текущая")
    store.add_result(row.dialog_id, row.cid, row.version, row.fp, row.result, run_id=row.run_id)
    return row.result


def adopt(store: Store, run_id: int, dialogs: list[str] | None, criteria: list[str] | None) -> dict[str, int]:
    """`POST /api/runs/{id}/adopt`: теневые ответы запуска compare (последний у пары) становятся текущими
    копией строки. Пропускаются пары, которые держит человек, и ответы прежнему смыслу критерия."""
    run = store.get_run(run_id)
    if run is None:
        raise NotFound(f"Запуск {run_id} не найден")
    if run.apply != "compare":
        raise Conflict(f"Запуск {run_id} заменял ответы сразу: принимать нечего")
    checklist = store.current_checklist()
    assert checklist is not None, "create_app сеет чек-лист на пустой базе"
    latest = {
        (r.dialog_id, r.cid): r
        for r in store.result_rows(run_id=run_id)
        if r.shadow
        and (dialogs is None or r.dialog_id in dialogs)
        and (criteria is None or r.cid in criteria)
    }
    items = [d for d in map(store.get_dialog, dict.fromkeys(i for i, _ in latest)) if d is not None]
    by_id = {d.id: d for d in items}
    fps = fingerprints(checklist)
    held = held_by_human(store, checklist, items)
    adopted = 0
    for (dlg, cid), row in latest.items():
        dialog = by_id[dlg]
        if fps[dialog.ch].get(cid) != row.fp or held(dialog, cid):
            continue
        store.add_result(dlg, cid, row.version, row.fp, row.result, run_id=run_id)
        adopted += 1
    return {"adopted": adopted, "skipped": len(latest) - adopted}
