"""Запуски оценки: план пар без текущего результата, диалоги по порядку, отмена и продолжение."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from cqa.adapters.store import RunRow, Store
from cqa.domain.models import Checklist, Cost, Criterion, Dialog
from cqa.domain.review import fingerprints
from cqa.services.errors import Conflict, NotFound
from cqa.services.ports import Evaluator
from cqa.services.state import current_results


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
    chosen = [c for c in checklist.criteria if criteria is None or c.id in criteria]
    if dialogs is None:
        items = store.list_dialogs()
    else:
        items = [d for d in map(store.get_dialog, dict.fromkeys(dialogs)) if d is not None]
    current = current_results(store, checklist, items)
    plan = []
    for dialog in items:
        todo = [c for c in chosen if c.id not in current.get(dialog.id, {})]
        if todo:
            plan.append((dialog, todo))
    return plan


class Runner:
    """Один активный запуск в фоне. `parallel` воркеров берут диалоги плана строго по очереди.

    `on_finish` получает событие `run.finished` по каждому запуску из `start` (вебхук интеграции).
    """

    def __init__(
        self,
        store: Store,
        evaluator: Evaluator,
        *,
        parallel: int,
        clock: Callable[[], float] = time.time,
        on_finish: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._evaluator = evaluator
        self._parallel = parallel
        self._clock = clock
        self._on_finish = on_finish
        self._cancel = asyncio.Event()
        self._active: int | None = None
        self._failed = 0  # пары упавших диалогов активного запуска: «done» за 0 с, ETA их не считает
        self._tasks: set[asyncio.Task[None]] = set()  # ссылка держит задачу от сборщика мусора
        # ponytail: в памяти процесса — после перезапуска состав старого запуска неизвестен (None)
        self._ids: dict[int, list[str]] = {}
        self._in_flight: set[str] = set()

    def use(self, evaluator: Evaluator) -> None:
        """Новый оценщик для следующих запусков (смена режима из интерфейса); во время запуска — Conflict."""
        if self._active is not None:
            raise Conflict(f"Запуск {self._active} ещё идёт: режим можно сменить после него")
        self._evaluator = evaluator

    def ensure_idle(self) -> None:
        """Conflict с номером, ходом и ETA активного запуска: клиент API видит, сколько ждать."""
        if self._active is not None:
            p = self.progress(self._active)
            extra = {"run_id": self._active, **{k: p[k] for k in ("done", "total", "eta_s")}}
            raise Conflict(f"Запуск {self._active} ещё идёт", **extra)

    def dialog_ids(self, run_id: int) -> list[str] | None:
        """Диалоги запуска из `start` этого процесса; None — запуск начат до перезапуска или не здесь."""
        return self._ids.get(run_id)

    def in_flight(self) -> set[str]:
        return set(self._in_flight)

    def start(self, dialogs: list[str] | None, criteria: list[str] | None) -> int:
        """Проверить аргументы, записать запуск и оценивать план в фоне. Вызывать внутри цикла событий."""
        self.ensure_idle()
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
        ids = list(dict.fromkeys(dialogs)) if dialogs is not None else [d.id for d, _ in plan]
        run_id = self._store.add_run(sum(len(cs) for _, cs in plan), self._clock())
        self._ids[run_id] = ids
        if not plan:
            self._store.finish_run(run_id, self._clock(), "done")
            if self._on_finish is not None:
                self._spawn(self._announce(run_id, ids))
            return run_id
        self._active = run_id
        self._failed = 0
        self._cancel = asyncio.Event()
        self._spawn(self._execute_and_announce(run_id, checklist, plan, ids))
        return run_id

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute_and_announce(
        self, run_id: int, checklist: Checklist, plan: list[tuple[Dialog, list[Criterion]]], ids: list[str]
    ) -> None:
        try:
            await self.execute(run_id, checklist, plan)
        finally:
            await self._announce(run_id, ids)

    async def _announce(self, run_id: int, ids: list[str]) -> None:
        """Событие без текста диалогов: счётчики, ошибки и id запрошенных диалогов."""
        if self._on_finish is None:
            return
        p = self.progress(run_id)
        keys = ("status", "done", "total", "errors")
        await self._on_finish(
            {"event": "run.finished", "run_id": run_id, **{k: p[k] for k in keys}, "dialog_ids": ids}
        )

    def progress(self, run_id: int) -> dict[str, Any]:
        row = self._run(run_id)
        failed = self._failed if run_id == self._active else 0
        eta = (
            None
            if row.status == "cancelled"
            else eta_seconds(row.done - failed, row.total - failed, self._clock() - row.started)
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
        fps = fingerprints(checklist)
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
        fps: dict[str, dict[str, str]],  # канал → id критерия → отпечаток
        dialog: Dialog,
        criteria: list[Criterion],
    ) -> None:
        started = self._clock()
        self._in_flight.add(dialog.id)
        try:
            out = await self._evaluator.evaluate(dialog, checklist, criteria)
        except Exception as exc:  # сбой одного диалога не останавливает запуск
            self._failed += len(criteria)
            self._store.record_progress(
                run_id, len(criteria), 0.0, 0, [f"{dialog.id}: {str(exc) or type(exc).__name__}"]
            )
            return
        finally:
            self._in_flight.discard(dialog.id)
        ms = round((self._clock() - started) * 1000)
        for e in out.results:
            self._store.add_result(dialog.id, e.cid, checklist.version, fps[dialog.ch][e.cid], e.result)
        calls = sum(e.result.calls for e in out.results)
        usd = sum(e.result.cost for e in out.results) + out.verifier_usd
        self._store.set_cost(dialog.id, Cost(calls=calls, verifier_calls=out.verifier_calls, usd=usd, ms=ms))
        answered = {e.cid for e in out.results}
        missing = [
            f"{dialog.id}/{c.id}: нет ответа модели, ждёт оценки" for c in criteria if c.id not in answered
        ]
        self._store.record_progress(run_id, len(criteria), usd, calls, missing)
