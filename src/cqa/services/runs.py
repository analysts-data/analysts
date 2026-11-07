"""Запуски оценки: план пар без текущего результата, диалоги по порядку, отмена и продолжение."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from cqa.adapters.store import RunRow, Store
from cqa.domain.models import Checklist, Cost, Criterion, Dialog
from cqa.domain.review import fingerprint
from cqa.services.errors import Conflict, NotFound
from cqa.services.ports import Evaluator


def eta_seconds(done: int, total: int, elapsed: float) -> int | None:
    if done >= total:
        return 0
    if done == 0:
        return None
    return round(elapsed / done * (total - done))


def plan_run(
    store: Store, checklist: Checklist, dialogs: list[str] | None, criteria: list[str] | None
) -> list[tuple[Dialog, list[Criterion]]]:
    """Пары без результата текущего смысла в порядке `dialogs` (None — порядок добавления).

    Неизвестные id пропускаются: их отсеивает `Runner.start`.
    """
    fps = {c.id: fingerprint(checklist, c) for c in checklist.criteria}
    current = store.current_results(fps)
    chosen = [c for c in checklist.criteria if criteria is None or c.id in criteria]
    if dialogs is None:
        items = store.list_dialogs()
    else:
        items = [d for d in map(store.get_dialog, dict.fromkeys(dialogs)) if d is not None]
    plan = []
    for dialog in items:
        todo = [c for c in chosen if c.id not in current.get(dialog.id, {})]
        if todo:
            plan.append((dialog, todo))
    return plan


class Runner:
    """Один активный запуск в фоне. `parallel` воркеров берут диалоги плана строго по очереди."""

    def __init__(
        self, store: Store, evaluator: Evaluator, *, parallel: int, clock: Callable[[], float] = time.time
    ) -> None:
        self._store = store
        self._evaluator = evaluator
        self._parallel = parallel
        self._clock = clock
        self._cancel = asyncio.Event()
        self._active: int | None = None
        self._tasks: set[asyncio.Task[None]] = set()  # ссылка держит задачу от сборщика мусора

    def start(self, dialogs: list[str] | None, criteria: list[str] | None) -> int:
        """Проверить аргументы, записать запуск и оценивать план в фоне. Вызывать внутри цикла событий."""
        if self._active is not None:
            raise Conflict(f"Запуск {self._active} ещё идёт")
        if dialogs is not None:
            unknown = [i for i in dict.fromkeys(dialogs) if self._store.get_dialog(i) is None]
            if unknown:
                raise NotFound(f"Диалоги не найдены: {', '.join(unknown)}")
        checklist = self._store.current_checklist()
        assert checklist is not None, "create_app сеет чек-лист на пустой базе"
        if criteria is not None:
            known = {c.id for c in checklist.criteria}
            unknown = [i for i in dict.fromkeys(criteria) if i not in known]
            if unknown:
                raise NotFound(f"Критериев нет в чек-листе v{checklist.version}: {', '.join(unknown)}")
        plan = plan_run(self._store, checklist, dialogs, criteria)
        run_id = self._store.add_run(sum(len(cs) for _, cs in plan), self._clock())
        if not plan:
            self._store.finish_run(run_id, self._clock(), "done")
            return run_id
        self._active = run_id
        self._cancel = asyncio.Event()
        task = asyncio.create_task(self.execute(run_id, checklist, plan))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

    def progress(self, run_id: int) -> dict[str, Any]:
        row = self._run(run_id)
        eta = (
            None
            if row.status == "cancelled"
            else eta_seconds(row.done, row.total, self._clock() - row.started)
        )
        return {
            "done": row.done,
            "total": row.total,
            "cost": row.cost,
            "calls": row.calls,
            "eta_s": eta,
            "errors": row.errors,
            "status": row.status,
        }

    def cancel(self, run_id: int) -> dict[str, str]:
        """Новые диалоги не начинаются; диалоги в полёте завершаются и сохраняются."""
        row = self._run(run_id)
        if row.status != "running":
            raise Conflict(f"Запуск {run_id} уже завершён: {row.status}")
        if run_id == self._active:
            self._cancel.set()
        else:  # строка без задачи в этом процессе: закрыть сразу
            self._store.finish_run(run_id, self._clock(), "cancelled")
        return {"status": "cancelled"}

    def _run(self, run_id: int) -> RunRow:
        row = self._store.get_run(run_id)
        if row is None:
            raise NotFound(f"Запуск {run_id} не найден")
        return row

    async def execute(
        self, run_id: int, checklist: Checklist, plan: list[tuple[Dialog, list[Criterion]]]
    ) -> None:
        fps = {c.id: fingerprint(checklist, c) for c in checklist.criteria}
        queue = iter(plan)  # общая очередь: next() не уступает цикл событий, порядок плана сохраняется

        async def worker() -> None:
            for dialog, criteria in queue:
                if self._cancel.is_set():
                    return
                await self._evaluate(run_id, checklist, fps, dialog, criteria)

        try:
            await asyncio.gather(*(worker() for _ in range(self._parallel)))
        finally:
            self._store.finish_run(run_id, self._clock(), "cancelled" if self._cancel.is_set() else "done")
            self._active = None

    async def _evaluate(
        self,
        run_id: int,
        checklist: Checklist,
        fps: dict[str, str],
        dialog: Dialog,
        criteria: list[Criterion],
    ) -> None:
        started = self._clock()
        try:
            out = await self._evaluator.evaluate(dialog, checklist, criteria)
        except Exception as exc:  # сбой одного диалога не останавливает запуск
            self._store.record_progress(
                run_id, len(criteria), 0.0, 0, [f"{dialog.id}: {exc or type(exc).__name__}"]
            )
            return
        ms = round((self._clock() - started) * 1000)
        for e in out.results:
            self._store.add_result(dialog.id, e.cid, checklist.version, fps[e.cid], e.result)
        calls = sum(e.result.calls for e in out.results)
        usd = sum(e.result.cost for e in out.results) + out.verifier_usd
        self._store.set_cost(dialog.id, Cost(calls=calls, verifier_calls=out.verifier_calls, usd=usd, ms=ms))
        answered = {e.cid for e in out.results}
        missing = [
            f"{dialog.id}/{c.id}: нет ответа модели, ждёт оценки" for c in criteria if c.id not in answered
        ]
        self._store.record_progress(run_id, len(criteria), usd, calls, missing)
