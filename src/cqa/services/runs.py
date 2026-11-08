"""Запуски оценки: план пар без текущего результата, диалоги по порядку, отмена и продолжение."""

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from cqa.adapters.store import RunRow, Store
from cqa.domain.models import Checklist, Cost, Criterion, Dialog, Product, ProductTag
from cqa.domain.review import fingerprints
from cqa.services.errors import Conflict, NotFound
from cqa.services.ports import Evaluator
from cqa.services.products import classify_plan
from cqa.services.state import current_results


class Classifier(Protocol):  # services.products.Classifier
    async def classify(self, dialog: Dialog, products: Sequence[Product]) -> ProductTag: ...


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
    items = _selected(store, dialogs)
    current = current_results(store, checklist, items)
    plan = []
    for dialog in items:
        todo = [c for c in chosen if c.id not in current.get(dialog.id, {})]
        if todo:
            plan.append((dialog, todo))
    return plan


def _selected(store: Store, dialogs: list[str] | None) -> list[Dialog]:
    if dialogs is None:
        return store.list_dialogs()
    return [d for d in map(store.get_dialog, dict.fromkeys(dialogs)) if d is not None]


def _no_products() -> dict[str, Any]:
    return {"done": 0, "total": 0, "errors": 0, "cost": 0.0}


class Runner:
    """Один активный запуск в фоне. `parallel` воркеров берут диалоги плана строго по очереди."""

    def __init__(
        self,
        store: Store,
        evaluator: Evaluator,
        *,
        parallel: int,
        clock: Callable[[], float] = time.time,
        classifier: Classifier | None = None,
    ) -> None:
        self._store = store
        self._evaluator = evaluator
        self._classifier = classifier  # None — темы не определяются
        # ponytail: прогресс тем в памяти процесса; после перезапуска у старых запусков нули
        self._products: dict[int, dict[str, Any]] = {}
        self._parallel = parallel
        self._clock = clock
        self._cancel = asyncio.Event()
        self._active: int | None = None
        self._failed = 0  # пары упавших диалогов активного запуска: «done» за 0 с, ETA их не считает
        self._tasks: set[asyncio.Task[None]] = set()  # ссылка держит задачу от сборщика мусора

    def use(self, evaluator: Evaluator, classifier: Classifier | None = None) -> None:
        """Новый оценщик (и классификатор) для следующих запусков; во время запуска — Conflict."""
        if self._active is not None:
            raise Conflict(f"Запуск {self._active} ещё идёт: режим можно сменить после него")
        self._evaluator = evaluator
        if classifier is not None:
            self._classifier = classifier

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
        products = self._store.products() or []
        todo = (
            classify_plan(self._store, products, _selected(self._store, dialogs))
            if self._classifier and products
            else []
        )
        run_id = self._store.add_run(sum(len(cs) for _, cs in plan), self._clock())
        self._products[run_id] = {**_no_products(), "total": len(todo)}
        if not plan and not todo:
            self._store.finish_run(run_id, self._clock(), "done")
            return run_id
        for d, _ in todo:
            self._store.set_product(d.id, ProductTag(status="pending"), "")
        self._active = run_id
        self._failed = 0
        self._cancel = asyncio.Event()
        task = asyncio.create_task(self.execute(run_id, checklist, plan, todo, products))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

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
            "products": dict(self._products.get(run_id) or _no_products()),
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
        self,
        run_id: int,
        checklist: Checklist,
        plan: list[tuple[Dialog, list[Criterion]]],
        todo: Sequence[tuple[Dialog, str]] = (),
        products: Sequence[Product] = (),
    ) -> None:
        """`plan` — пары для оценки, `todo` — диалоги для темы с ключом кэша: одна задача на диалог."""
        fps = fingerprints(checklist)
        keys = {d.id: k for d, k in todo}
        jobs = {d.id: (d, cs) for d, cs in plan}  # сначала порядок плана, затем диалоги только для темы
        for d, _ in todo:
            jobs.setdefault(d.id, (d, []))
        queue = iter(jobs.values())  # общая очередь: next() не уступает цикл событий, порядок сохраняется

        async def worker() -> None:
            for dialog, criteria in queue:
                if self._cancel.is_set():
                    return
                steps = [self._evaluate(run_id, checklist, fps, dialog, criteria)] if criteria else []
                if dialog.id in keys:
                    steps.append(self._classify(run_id, dialog, keys[dialog.id], products))
                await asyncio.gather(*steps)

        cancelled = True  # прерванная задача (Ctrl-C, остановка сервера) — не «done»
        try:
            await asyncio.gather(*(worker() for _ in range(self._parallel)))
            cancelled = self._cancel.is_set()
        finally:
            self._store.clear_pending_products()
            self._store.finish_run(run_id, self._clock(), "cancelled" if cancelled else "done")
            self._active = None

    async def _classify(self, run_id: int, dialog: Dialog, key: str, products: Sequence[Product]) -> None:
        """Тема диалога; сбой — статус error с текстом у темы, оценку и `errors` запуска не трогает."""
        assert self._classifier is not None, "todo строится только с классификатором"
        try:
            tag = await self._classifier.classify(dialog, products)
        except Exception as exc:
            tag = ProductTag(status="error", error=str(exc) or type(exc).__name__)
        self._store.set_product(dialog.id, tag, key if tag.status == "done" else "")
        counts = self._products.setdefault(run_id, _no_products())
        counts["done"] += 1
        counts["errors"] += tag.status == "error"
        counts["cost"] += tag.cost

    async def _evaluate(
        self,
        run_id: int,
        checklist: Checklist,
        fps: dict[str, dict[str, str]],  # канал → id критерия → отпечаток
        dialog: Dialog,
        criteria: list[Criterion],
    ) -> None:
        started = self._clock()
        try:
            out = await self._evaluator.evaluate(dialog, checklist, criteria)
        except Exception as exc:  # сбой одного диалога не останавливает запуск
            self._failed += len(criteria)
            self._store.record_progress(
                run_id, len(criteria), 0.0, 0, [f"{dialog.id}: {str(exc) or type(exc).__name__}"]
            )
            return
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
