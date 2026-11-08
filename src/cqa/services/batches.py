"""Пакетная обработка: задание делится на батчи, одна очередь процесса отдаёт их `Runner` по одному.

Очередь — клиент `Runner`: каждый батч — обычный запуск, правило одного активного запуска сохраняется.
"""

import asyncio
import itertools
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Literal

from cqa.adapters.batches import BatchRunRow, BatchStore, ItemRow, ItemStatus, JobRow, JobStatus, Priority
from cqa.adapters.store import RunRow, Store
from cqa.domain.ingest import _AT
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.runs import Runner, plan_run

log = logging.getLogger("cqa.batches")

Action = Literal["pause", "resume", "cancel", "retry"]
PRIORITY: tuple[Priority, ...] = ("high", "normal", "low")
RECENT = 3  # ETA по скорости последних стольких завершённых батчей
RESTART_NOTE = (
    "Сервер перезапускался: задание на паузе, продолжите вручную. Само не продолжается — после "
    "перезапуска могли смениться модель, ключи и режим данных, а оценка тратит деньги."
)


def next_job(jobs: Sequence[JobRow]) -> JobRow | None:
    """Следующее задание очереди: высокий приоритет первым, внутри приоритета — по порядку создания."""
    active = [j for j in jobs if j.status in ("queued", "running")]
    return min(active, key=lambda j: (PRIORITY.index(j.priority), j.id), default=None)


def transition(status: JobStatus, action: Action, failed: int) -> JobStatus | None:
    """Новый статус задания или None, если действие в этом статусе недоступно."""
    if action == "pause" and status in ("queued", "running"):
        return "paused"
    if action == "resume" and status == "paused":
        return "queued"
    if action == "cancel" and status in ("queued", "running", "paused"):
        return "cancelled"
    if action == "retry" and status != "cancelled" and failed:
        return "queued" if status in ("done", "failed") else status
    return None


def pace(recent: Sequence[tuple[int, float]], remaining: int) -> tuple[float | None, int | None, str]:
    """(диалогов в минуту, ETA в секундах, основание) по (диалогов, секунд) завершённых батчей."""
    last = list(recent)[-RECENT:]
    n, secs = sum(k for k, _ in last), sum(s for _, s in last)
    if not n or secs <= 0:
        return None, 0 if remaining == 0 else None, "нет завершённых батчей"
    basis = "по скорости последнего батча" if len(last) == 1 else f"по скорости последних {len(last)} батчей"
    return round(n / secs * 60, 1), round(remaining * secs / n), basis


def outcomes(
    ids: Sequence[str], errors: Sequence[str], cancelled: bool
) -> dict[str, tuple[ItemStatus, str | None]]:
    """Итог диалогов батча по `errors` запуска: «<id>: …» — сбой, «<id>/<cid>: …» — нет ответа модели.

    Отменённый запуск: диалоги без ошибки остаются в очереди (могли не начаться).
    """
    out: dict[str, tuple[ItemStatus, str | None]] = {}
    for i in ids:
        mine = [e[len(i) + 1 :].lstrip() for e in errors if e.startswith((f"{i}: ", f"{i}/"))]
        if mine:
            out[i] = ("error", "; ".join(mine))
        elif not cancelled:
            out[i] = ("done", None)
    return out


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts is not None else None


def _day(at: str) -> tuple[int, int]:
    # ponytail: в `at` нет года (dd.mm HH:MM) — сравнение в пределах года; год появится в at — сравнить даты
    parsed = datetime.strptime(at, _AT)
    return parsed.month, parsed.day


class Batches:
    def __init__(
        self,
        store: Store,
        jobs: BatchStore,
        runner: Runner,
        *,
        clock: Callable[[], float] = time.time,
        poll_s: float = 0.2,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._runner = runner
        self._clock = clock
        self._poll_s = poll_s  # опрос конца запуска и освобождения Runner
        self._wake = asyncio.Event()

    # --- выбор и создание ---

    def select(self, flt: Mapping[str, Any]) -> list[str]:
        """Диалоги по фильтру в порядке добавления. Поле, которого нет у диалога, ничего не находит."""
        unscored_only = flt.get("unscored_only", True)
        since: date | None = flt.get("since")
        equal = {k: v for k, v in flt.items() if k not in ("unscored_only", "since") and v is not None}
        todo: set[str] = set()
        if unscored_only:
            checklist = self._store.current_checklist()
            assert checklist is not None, "create_app сеет чек-лист на пустой базе"
            todo = {d.id for d, _ in plan_run(self._store, checklist, None, None)}
        return [
            d.id
            for d in self._store.list_dialogs()
            if all(getattr(d, k, None) == v for k, v in equal.items())
            and (since is None or _day(d.at) >= (since.month, since.day))
            and (not unscored_only or d.id in todo)
        ]

    def create(
        self,
        dialogs: list[str] | None,
        flt: Mapping[str, Any] | None,
        *,
        batch_size: int,
        priority: Priority,
        force: bool,
    ) -> dict[str, Any]:
        if (dialogs is None) == (flt is None):
            raise Invalid("Нужен ровно один из dialogs или filter")
        if (
            force
        ):  # ponytail: Runner на main оценивает только пары без результата; force — с повторной проверкой
            raise Invalid("force пока недоступен: батч оценивает только пары без текущего результата")
        if dialogs is not None:
            ids = list(dict.fromkeys(dialogs))
            unknown = [i for i in ids if self._store.get_dialog(i) is None]
            if unknown:
                raise NotFound(f"Диалоги не найдены: {', '.join(unknown)}")
        else:
            ids = self.select(flt or {})
        if not ids:
            raise Invalid("Фильтру не соответствует ни один диалог")
        batches = list(itertools.batched(ids, batch_size))
        job_id = self._jobs.add_job(priority, batch_size, force, self._clock(), batches)
        self._wake.set()
        return self.view(job_id)

    # --- управление ---

    def act(self, job_id: int, action: Action) -> dict[str, Any]:
        job = self._job(job_id)
        failed = sum(i.status == "error" for i in self._jobs.items(job_id))
        to = transition(job.status, action, failed)
        if to is None:
            if action == "retry" and job.status != "cancelled":
                raise Conflict(f"В задании {job_id} нет диалогов с ошибкой")
            raise Conflict(f"Задание {job_id} в статусе {job.status}: {action} недоступно")
        if action == "retry":
            self._jobs.retry_errors(job_id)
        # пауза и отмена не прерывают батч в работе: он дорабатывает, следующий не начинается
        self._jobs.set_status(job_id, to, None if action in ("resume", "retry") else job.note)
        if to == "queued":
            self._wake.set()
        return self.view(job_id)

    def recover(self) -> None:
        """Старт сервера: незаконченные задания — на паузу с пояснением, без автопродолжения."""
        self._jobs.pause_unfinished(RESTART_NOTE)

    # --- состояние ---

    def _job(self, job_id: int) -> JobRow:
        job = self._jobs.job(job_id)
        if job is None:
            raise NotFound(f"Задание {job_id} не найдено")
        return job

    def view(self, job_id: int) -> dict[str, Any]:
        job = self._job(job_id)
        items = self._jobs.items(job_id)
        runs = self._jobs.batch_runs(job_id)
        pending = sum(i.status == "queued" for i in items)
        speed, eta, basis = pace(
            [(r.n, r.finished - r.started) for r in runs if r.finished is not None], pending
        )
        return {
            "id": job.id,
            "status": job.status,
            "priority": job.priority,
            "batch_size": job.batch_size,
            "force": job.force,
            "note": job.note,
            "created": _iso(job.created),
            "total": len(items),
            "done": sum(i.status == "done" for i in items),
            "errors": sum(i.status == "error" for i in items),
            "pending": pending,
            "cost": sum(r.cost for r in runs),
            "throughput_per_min": speed,
            "eta_s": eta if job.status in ("queued", "running") else None,
            "eta_basis": basis,
            "batches": [
                self._batch(no, list(its), [r for r in runs if r.batch == no])
                for no, its in itertools.groupby(items, key=lambda i: i.batch)
            ],
            "failed": [{"dialog": i.dialog_id, "error": i.error} for i in items if i.status == "error"],
        }

    @staticmethod
    def _batch(no: int, items: list[ItemRow], runs: list[BatchRunRow]) -> dict[str, Any]:
        finished = [r.finished for r in runs if r.finished is not None]
        over = runs and all(i.status != "queued" for i in items)
        return {
            "no": no,
            "n": len(items),
            "done": sum(i.status == "done" for i in items),
            "errors": sum(i.status == "error" for i in items),
            "started": _iso(runs[0].started) if runs else None,
            "finished": _iso(max(finished)) if over and finished else None,
            "cost": sum(r.cost for r in runs),
            "run_id": runs[-1].run_id if runs else None,
        }

    def summaries(self) -> list[dict[str, Any]]:
        """Задания, новые первыми, без таблицы батчей и списка ошибок."""
        out = []
        for job in self._jobs.jobs():
            view = self.view(job.id)
            out.append({k: v for k, v in view.items() if k not in ("batches", "failed")})
        return out

    # --- очередь ---

    async def work(self) -> None:
        """Цикл очереди; запускает lifespan приложения."""
        while True:
            try:
                busy = await self.step()
            except Exception:  # сбой очереди не роняет сервер; следующее действие разбудит её снова
                log.exception("очередь батчей")
                busy = False
            if not busy:
                self._wake.clear()
                await self._wake.wait()

    async def step(self) -> bool:
        """Один батч следующего задания. False — очередь пуста."""
        job = next_job(self._jobs.jobs())
        if job is None:
            return False
        self._jobs.claim(job.id)
        queued = [i for i in self._jobs.items(job.id) if i.status == "queued"]
        if queued:
            batch = queued[0].batch
            ids = [i.dialog_id for i in queued if i.batch == batch]
            run_id = await self._start(job.id, ids)
            if run_id is not None:
                self._jobs.add_batch_run(run_id, job.id, batch, len(ids))
                run = await self._finished(run_id)
                cancelled = run.status == "cancelled"
                self._jobs.set_items(job.id, outcomes(ids, run.errors, cancelled))
                if cancelled and self._job(job.id).status == "running":
                    self._jobs.set_status(job.id, "paused", f"Запуск {run_id} батча {batch} отменён вручную")
        self._settle(job.id)
        return True

    async def _start(self, job_id: int, ids: list[str]) -> int | None:
        while True:
            try:
                return self._runner.start(ids, None)
            except Conflict:  # идёт запуск вне очереди: ждать его, второй активный запуск не начинать
                await asyncio.sleep(self._poll_s)
                if self._job(job_id).status != "running":  # пауза или отмена, пока ждали
                    return None
            except Exception as exc:  # сбой батча не останавливает задание
                self._jobs.set_items(job_id, {i: ("error", str(exc) or type(exc).__name__) for i in ids})
                return None

    async def _finished(self, run_id: int) -> RunRow:
        while True:
            run = self._store.get_run(run_id)
            assert run is not None
            if run.status != "running":
                return run
            await asyncio.sleep(self._poll_s)

    def _settle(self, job_id: int) -> None:
        """Диалогов в очереди не осталось — задание закончено: failed, если не оценён ни один."""
        job = self._job(job_id)
        items = self._jobs.items(job_id)
        if job.status in ("queued", "running", "paused") and all(i.status != "queued" for i in items):
            self._jobs.set_status(job_id, "failed" if all(i.status == "error" for i in items) else "done")
