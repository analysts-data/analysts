"""Запуски оценки: план пар без текущего результата или повторная проверка, диалоги по порядку,
отмена и продолжение, список запусков и сравнение двух."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from cqa.adapters.store import DialogStatus, RunRow, Store
from cqa.domain.agreement import compare_answers
from cqa.domain.models import Checklist, Cost, Criterion, Dialog
from cqa.domain.review import fingerprints
from cqa.services.answers import MANUAL
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.ports import Evaluator
from cqa.services.state import current_results
from cqa.services.sufficiency import assess_dialogs

log = logging.getLogger(__name__)


def eta_seconds(done: int, total: int, elapsed: float) -> int | None:
    if done >= total:
        return 0
    if done == 0:
        return None
    return round(elapsed / done * (total - done))


Plan = list[tuple[Dialog, list[Criterion]]]
ApplyMode = Literal["replace", "compare"]
CONFIRM_OVER = 5  # повторная проверка без списка диалогов больше стольких диалогов ждёт confirm: true


def _select(
    store: Store, checklist: Checklist, dialogs: list[str] | None, criteria: list[str] | None
) -> tuple[list[Dialog], list[Criterion]]:
    """Диалоги в порядке `dialogs` (None — порядок добавления) и критерии; неизвестные id пропускаются.

    Диалоги «Недостаточно данных» (block) модели не отправляются: их считает `insufficient`.
    """
    chosen = [c for c in checklist.criteria if criteria is None or c.id in criteria]
    blocked = set(insufficient(store, dialogs))
    return [d for d in _requested(store, dialogs) if d.id not in blocked], chosen


def _requested(store: Store, dialogs: list[str] | None) -> list[Dialog]:
    if dialogs is None:
        return store.list_dialogs()
    return [d for d in map(store.get_dialog, dict.fromkeys(dialogs)) if d is not None]


def insufficient(store: Store, dialogs: list[str] | None) -> list[str]:
    """Диалоги запуска со статусом block: «пропущено: недостаточно данных»."""
    items = _requested(store, dialogs)
    verdicts = assess_dialogs(store, items)
    return [d.id for d in items if verdicts[d.id].status == "block"]


def _plan(items: list[Dialog], chosen: list[Criterion], skip: Callable[[Dialog, Criterion], bool]) -> Plan:
    plan = []
    for dialog in items:
        todo = [c for c in chosen if not skip(dialog, c)]
        if todo:
            plan.append((dialog, todo))
    return plan


def plan_run(
    store: Store, checklist: Checklist, dialogs: list[str] | None, criteria: list[str] | None
) -> Plan:
    """Пары без результата текущего смысла. Неизвестные id пропускаются: их отсеивает `Runner.start`."""
    items, chosen = _select(store, checklist, dialogs, criteria)
    current = current_results(store, checklist, items)
    return _plan(items, chosen, lambda d, c: c.id in current.get(d.id, {}))


def plan_rerun(
    store: Store, checklist: Checklist, dialogs: list[str] | None, criteria: list[str] | None
) -> tuple[Plan, dict[str, int]]:
    """Повторная проверка: все выбранные пары, кроме тех, что держит человек, — текущий ответ ручной
    или по паре текущего смысла есть апелляция на рассмотрении или решение.
    Второе — диалог → число таких пар (только диалоги, где они есть)."""
    items, chosen = _select(store, checklist, dialogs, criteria)
    held = held_by_human(store, checklist, items)
    held_by = {d.id: n for d in items if (n := sum(held(d, c.id) for c in chosen))}
    return _plan(items, chosen, lambda d, c: held(d, c.id)), held_by


def held_by_human(store: Store, checklist: Checklist, dialogs: list[Dialog]) -> Callable[[Dialog, str], bool]:
    """Пару держит человек: текущий ответ ручной или по паре текущего смысла есть апелляция на
    рассмотрении или решение. Такую пару модель не перезаписывает. `cid` — из текущего чек-листа."""
    fps = fingerprints(checklist)
    current = current_results(store, checklist, dialogs)
    appealed = {(a.dlg, a.cid, fp) for a, fp in store.list_appeals() if a.status != "closed"}

    def held(d: Dialog, cid: str) -> bool:
        result = current.get(d.id, {}).get(cid)
        return (result is not None and result.model == MANUAL) or (d.id, cid, fps[d.ch][cid]) in appealed

    return held


def list_runs(store: Store) -> list[dict[str, Any]]:
    """`GET /api/runs`: последние запуски, новые первыми."""
    return [
        {
            "id": r.id,
            "created": datetime.fromtimestamp(r.started, UTC).isoformat(),
            "status": r.status,
            "model": r.model,
            "checklist_version": r.checklist_version,
            "total": r.total,
            "done": r.done,
            "cost": r.cost,
            "errors_count": len(r.errors),
            "force": r.force,
            "skipped": r.skipped,
            "apply": r.apply,
            "override": r.override,
        }
        for r in store.list_runs()
    ]


def compare_runs(store: Store, a: int, b: int) -> dict[str, Any]:
    """`GET /api/runs/compare`: пары, отвеченные в обоих запусках; у пары берётся последняя строка запуска."""
    answers = []
    for run_id in (a, b):
        if store.get_run(run_id) is None:
            raise NotFound(f"Запуск {run_id} не найден")
        answers.append({(r.dialog_id, r.cid): r.result.a for r in store.result_rows(run_id=run_id)})
    checklist = store.current_checklist()
    assert checklist is not None, "create_app сеет чек-лист на пустой базе"
    return {"a": a, "b": b, **compare_answers(answers[0], answers[1], checklist)}


class Runner:
    """Один активный запуск в фоне. `parallel` воркеров берут диалоги плана строго по очереди."""

    def __init__(
        self,
        store: Store,
        evaluator: Evaluator,
        *,
        parallel: int,
        clock: Callable[[], float] = time.time,
        on_finish: Callable[[], Awaitable[object]] | None = None,  # проверка алертов после запуска
    ) -> None:
        self._on_finish = on_finish
        self._store = store
        self._evaluator = evaluator
        self._parallel = parallel
        self._clock = clock
        self._cancel = asyncio.Event()
        self._active: int | None = None
        self._failed = 0  # пары упавших диалогов активного запуска: «done» за 0 с, ETA их не считает
        # ponytail: в памяти процесса, после перезапуска 0; колонка в runs, если понадобится в истории
        self._insufficient: dict[int, int] = {}  # запуск → пропущено диалогов «Недостаточно данных»
        self._tasks: set[asyncio.Task[None]] = set()  # ссылка держит задачу от сборщика мусора

    def use(self, evaluator: Evaluator) -> None:
        """Новый оценщик для следующих запусков (смена режима из интерфейса); во время запуска — Conflict."""
        if self._active is not None:
            raise Conflict(f"Запуск {self._active} ещё идёт: режим можно сменить после него")
        self._evaluator = evaluator

    def start(
        self,
        dialogs: list[str] | None,
        criteria: list[str] | None,
        *,
        force: bool = False,
        confirm: bool = False,
        model: str | None = None,
        apply: ApplyMode = "replace",
        override: Mapping[str, Any] | None = None,
        evaluator: Evaluator | None = None,
        checklist: Checklist | None = None,
    ) -> int:
        """Проверить аргументы, записать запуск и оценивать план в фоне. Вызывать внутри цикла событий.

        `force` — повторная проверка (`plan_rerun`); без списка `dialogs` больше `CONFIRM_OVER` диалогов
        нужен `confirm`. `model` — подпись модели в списке запусков. Перепроверка другой моделью:
        `evaluator` только на этот запуск, `override` — его настройки для истории; `apply: "compare"` —
        ответы теневые, текущими их делает `adopt` или `restore`. `override` и `compare` — всегда `force`.
        `checklist` — несохранённый черновик для песочницы: ответы пишутся с его отпечатками и становятся
        текущими только после сохранения черновика; по умолчанию — текущая версия.
        """
        force = force or apply == "compare" or override is not None
        if self._active is not None:
            raise Conflict(f"Запуск {self._active} ещё идёт")
        if dialogs is not None:
            unknown = [i for i in dict.fromkeys(dialogs) if self._store.get_dialog(i) is None]
            if unknown:
                raise NotFound(f"Диалоги не найдены: {', '.join(unknown)}")
        checklist = self._store.current_checklist() if checklist is None else checklist
        assert checklist is not None, "create_app сеет чек-лист на пустой базе"
        if criteria is not None:
            known = {c.id for c in checklist.criteria}
            unknown = [i for i in dict.fromkeys(criteria) if i not in known]
            if unknown:
                raise NotFound(f"Критериев нет в чек-листе v{checklist.version}: {', '.join(unknown)}")
        plan, held = (
            plan_rerun(self._store, checklist, dialogs, criteria)
            if force
            else (plan_run(self._store, checklist, dialogs, criteria), {})
        )
        if force and dialogs is None and not confirm and len(plan) > CONFIRM_OVER:
            raise Invalid(f"Подтвердите перезапуск {len(plan)} диалогов")
        run_id = self._store.add_run(
            sum(len(cs) for _, cs in plan),
            self._clock(),
            model=model,
            checklist_version=checklist.version,
            force=force,
            skipped=sum(held.values()),
            apply=apply,
            override=override,
        )
        planned = {d.id for d, _ in plan}
        rows: list[tuple[str, DialogStatus, int, int]] = [
            (d.id, "queued", len(cs), held.get(d.id, 0)) for d, cs in plan
        ]
        rows += [(i, "skipped", 0, n) for i, n in held.items() if i not in planned]
        self._store.queue_dialogs(run_id, rows)
        self._insufficient[run_id] = len(insufficient(self._store, dialogs))
        if not plan:
            self._store.finish_run(run_id, self._clock(), "done")
            return run_id
        self._active = run_id
        self._failed = 0
        self._cancel = asyncio.Event()
        task = asyncio.create_task(
            self.execute(run_id, checklist, plan, evaluator=evaluator, shadow=apply == "compare")
        )
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
            "skipped": row.skipped,
            "insufficient": self._insufficient.get(run_id, 0),
            "dialogs": self._store.run_dialogs(run_id),
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
        plan: Plan,
        *,
        evaluator: Evaluator | None = None,
        shadow: bool = False,
    ) -> None:
        fps = fingerprints(checklist)
        use = evaluator or self._evaluator
        queue = iter(plan)  # общая очередь: next() не уступает цикл событий, порядок плана сохраняется

        async def worker() -> None:
            for dialog, criteria in queue:
                if self._cancel.is_set():
                    return
                await self._evaluate(run_id, checklist, fps, dialog, criteria, use, shadow)

        cancelled = True  # прерванная задача (Ctrl-C, остановка сервера) — не «done»
        try:
            await asyncio.gather(*(worker() for _ in range(self._parallel)))
            cancelled = self._cancel.is_set()
        finally:
            self._store.finish_run(run_id, self._clock(), "cancelled" if cancelled else "done")
            self._active = None
        if self._on_finish is not None:
            try:
                await self._on_finish()
            except Exception:  # алерты вторичны: запуск уже сохранён
                log.exception("проверка алертов после запуска %s", run_id)

    async def _evaluate(
        self,
        run_id: int,
        checklist: Checklist,
        fps: dict[str, dict[str, str]],  # канал → id критерия → отпечаток
        dialog: Dialog,
        criteria: list[Criterion],
        evaluator: Evaluator,
        shadow: bool,
    ) -> None:
        started = self._clock()
        self._store.set_dialog_status(run_id, dialog.id, "evaluating")
        try:
            out = await evaluator.evaluate(dialog, checklist, criteria)
        except Exception as exc:  # сбой одного диалога не останавливает запуск
            self._failed += len(criteria)
            error = str(exc) or type(exc).__name__
            self._store.set_dialog_status(run_id, dialog.id, "error", error=error)
            self._store.record_progress(run_id, len(criteria), 0.0, 0, [f"{dialog.id}: {error}"])
            return
        ms = round((self._clock() - started) * 1000)
        for e in out.results:
            self._store.add_result(
                dialog.id, e.cid, checklist.version, fps[dialog.ch][e.cid], e.result, run_id, shadow
            )
        calls = sum(e.result.calls for e in out.results)
        usd = sum(e.result.cost for e in out.results) + out.verifier_usd
        self._store.set_cost(dialog.id, Cost(calls=calls, verifier_calls=out.verifier_calls, usd=usd, ms=ms))
        answered = {e.cid for e in out.results}
        missing = [c.id for c in criteria if c.id not in answered]
        note = f"нет ответа модели, ждёт оценки: {', '.join(missing)}" if missing else None
        self._store.set_dialog_status(run_id, dialog.id, "done", done=len(answered), error=note)
        self._store.record_progress(
            run_id,
            len(criteria),
            usd,
            calls,
            [f"{dialog.id}/{cid}: нет ответа модели, ждёт оценки" for cid in missing],
        )
