"""Автоматизация: по расписанию синхронизировать источники, отдать модели новые диалоги в пределах лимитов,
бюджета и тихих часов, затем шаги после оценки. Один цикл за раз; сбой цикла пишется и не роняет сервер.

Внешние куски — за портами `Ports`. `wire` собирает их на том, что есть в main (Syncer, Runner);
строки с «→» меняются на реестр источников, батч-задачи, достаточность, алерты и журнал одной строкой.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from cqa.adapters.batches import Priority
from cqa.adapters.store import Store
from cqa.domain.automation import (
    AutomationSettings,
    Phase,
    allowance,
    candidates,
    check,
    due_sources,
    next_run_at,
    state,
    totals,
)
from cqa.domain.checklist_export import excel_csv
from cqa.domain.models import Dialog
from cqa.domain.review import ASTANA
from cqa.services.audit import Actor, record
from cqa.services.batches import Batches
from cqa.services.errors import Conflict, NotFound, Upstream
from cqa.services.runs import Runner, plan_run
from cqa.services.state import current_results
from cqa.services.sufficiency import assess_dialogs
from cqa.services.sync import Syncer

ACTOR = "Автоматизация"
AUTOMATION = Actor(None, ACTOR)  # журнал действий: автоматические действия от имени «Автоматизация»
TICK_S = 15.0  # планировщик просыпается раз в 15 с и решает, пора ли цикл
POLL_S = 0.5
Trigger = Literal["schedule", "manual"]
Step = Callable[[list[str]], Awaitable[Any]]
log = logging.getLogger("cqa.automation")


def _log_audit(action: str, target_type: str, target_id: str, details: Mapping[str, Any]) -> None:
    log.info("%s: %s %s %s %s", ACTOR, action, target_type, target_id, dict(details))


@dataclass
class Ports:
    sources: Callable[[], list[str]]  # коды источников, которые можно синхронизировать
    sync: Callable[[str], Awaitable[Mapping[str, Any]]]  # → {added, skipped, error}
    evaluate: Callable[[list[str], Priority, Callable[[float], bool]], Awaitable[Mapping[str, Any]]]
    source_of: Callable[[Dialog], str]
    blocked: Callable[[Dialog], bool] = lambda d: False
    notify: Callable[[dict[str, Any]], Any] = lambda hit: None
    audit: Callable[[str, str, str, Mapping[str, Any]], None] = _log_audit
    steps: Mapping[str, Step] = field(default_factory=dict)


def _iso(dt: datetime) -> str:
    return dt.astimezone(ASTANA).isoformat(timespec="seconds")


def _merge(base: Any, over: Any) -> Any:
    if not (isinstance(base, dict) and isinstance(over, dict)):
        return over
    return {**base, **{k: _merge(base.get(k), v) for k, v in over.items()}}


async def batch_evaluate(
    batches: Batches,
    runner: Runner,
    ids: list[str],
    priority: Priority,
    stop: Callable[[float], bool],
    *,
    poll_s: float = POLL_S,
) -> dict[str, Any]:
    """Пачка — задание очереди батчей с приоритетом; stop(цена) → отмена задания и его запуска
    (диалоги в полёте дописываются). Задание на паузе (из «Батчей») — цикл не ждёт, остаток там.

    Запрет реальных данных и обезличивание — внутри оценщика Runner, как у ручного запуска.
    """
    job_id = batches.create(ids, None, batch_size=len(ids), priority=priority, force=False)["id"]
    stopped = False
    while (view := batches.view(job_id))["status"] in ("queued", "running"):
        if not stopped and stop(view["cost"]):
            stopped = True
            with contextlib.suppress(Conflict):
                batches.act(job_id, "cancel")
            run_id = view["batches"][0]["run_id"]
            if run_id is not None:
                with contextlib.suppress(Conflict, NotFound):
                    runner.cancel(run_id)
        await asyncio.sleep(poll_s)
    errors = [f"{f['dialog']}: {f['error']}" for f in view["failed"]]
    return {"evaluated": view["done"], "cost": view["cost"], "errors": errors}


def wire(
    store: Store, syncer: Syncer, runner: Runner, batches: Batches, prosody: Callable[[str], Awaitable[Any]]
) -> Ports:
    """Порты на кусках из main. Источник один — ссылка организаторов, код «org», как в реестре источников."""

    async def sync(source_id: str) -> Mapping[str, Any]:  # → реестр: registry.sync(source_id)
        await syncer.sync()
        st = syncer.status() or {}
        return {"added": st.get("added", 0), "skipped": st.get("skipped", 0), "error": st.get("error")}

    async def prosody_for_calls(ids: list[str]) -> None:
        for i in ids:
            dialog = store.get_dialog(i)
            if dialog is not None and dialog.ch == "call" and store.audio_url(i):
                with contextlib.suppress(NotFound, Upstream):
                    await prosody(i)

    def source_of(d: Dialog) -> str:  # → d.source_id; до реестра — как его перенос старых диалогов
        return "paste" if d.id.startswith("paste-") else "org" if store.org_source() else "file"

    return Ports(
        sources=lambda: ["org"] if store.org_source() else [],  # → [s.id for s in registry if s.enabled]
        sync=sync,
        evaluate=lambda ids, priority, stop: batch_evaluate(batches, runner, ids, priority, stop),
        source_of=source_of,
        blocked=lambda d: assess_dialogs(store, [d])[d.id].status == "block",
        # notify → lambda h: store.add_alerts([h], now) — когда алерты (#87) в main
        audit=lambda action, kind, target, details: record(store, AUTOMATION, action, kind, target, details),
        steps={"prosody_for_calls": prosody_for_calls},  # → + classify_products, evaluate_alerts
    )


class Automation:
    def __init__(
        self,
        store: Store,
        ports: Ports,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(ASTANA),
        tick_s: float = TICK_S,
    ) -> None:
        self._store = store
        self._ports = ports
        self._clock = clock
        self._tick_s = tick_s
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[dict[str, Any]] | None = None
        self._phase: Phase | None = None
        self._current: dict[str, Any] | None = None
        self._last_sync: dict[str, datetime] = {}
        self._budget_day: str | None = None

    # --- настройки и управление ---

    def settings(self) -> AutomationSettings:
        saved, _ = check(self._store.automation("settings") or {})
        return saved or AutomationSettings()

    def put(self, raw: Any) -> tuple[AutomationSettings | None, list[dict[str, Any]]]:
        """Тело сливается с сохранёнными настройками; при ошибках ничего не сохраняется."""
        saved, errors = check(_merge(self.settings().model_dump(mode="json", by_alias=True), raw))
        if saved is not None:
            self._store.set_automation("settings", saved.model_dump(mode="json", by_alias=True))
        return saved, errors

    def paused(self) -> bool:
        return bool(self._store.automation("paused"))

    def pause(self) -> dict[str, Any]:
        self._store.set_automation("paused", True)
        return self.status()

    def resume(self) -> dict[str, Any]:
        self._store.set_automation("paused", False)
        return self.status()

    def owns_sync(self) -> bool:
        """Синхронизацию ведёт автоматизация по своему расписанию: прежний 5-минутный цикл Syncer ждёт."""
        s = self.settings()
        return s.enabled and s.sync.enabled

    def busy(self) -> bool:
        return self._lock.locked() or (self._task is not None and not self._task.done())

    def run_now(self) -> dict[str, Any]:
        if not self.settings().enabled:
            raise Conflict("Автоматизация выключена: включите её, чтобы запустить цикл")
        if self.paused():
            raise Conflict("Автоматизация на паузе: продолжите её, чтобы запустить цикл")
        if self.busy():
            raise Conflict("Цикл автоматизации уже идёт")
        self._task = asyncio.create_task(self.cycle("manual"))
        return self.status()

    def cycles(self, limit: int) -> list[dict[str, Any]]:
        return self._store.cycles(limit=limit)

    def status(self) -> dict[str, Any]:
        s, now = self.settings(), self._clock()
        t = totals(
            self._store.cycles(since=_iso(now - timedelta(days=1))), now, budget=s.evaluate.daily_budget_usd
        )
        last = self._current or next(iter(self._store.cycles(limit=1)), None)
        paused = self.paused()
        started = datetime.fromisoformat(last["started"]) if last else None
        nxt = next_run_at(s, paused=paused, last_started=started, now=now)
        return {
            "state": state(s, now, phase=self._phase, paused=paused, spent_today=t["cost_usd"]),
            "next_run_at": _iso(max(nxt, now)) if nxt else None,
            "last_cycle": last,
            "today": {k: t[k] for k in ("dialogs_evaluated", "cost_usd", "budget_left")},
            "queue_length": len(self.queue(s)),
        }

    def queue(self, s: AutomationSettings) -> list[str]:
        checklist = self._store.current_checklist()
        if checklist is None:
            return []
        dialogs = self._store.list_dialogs()
        return candidates(
            s.evaluate,
            dialogs,
            todo={d.id for d, _ in plan_run(self._store, checklist, None, None)},
            scored=set(current_results(self._store, checklist, dialogs)),
            source={d.id: self._ports.source_of(d) for d in dialogs},
            blocked={d.id for d in dialogs if self._ports.blocked(d)},
        )

    # --- планировщик и цикл ---

    async def run(self) -> None:
        """Задача lifespan: тик раз в tick_s; отмена останавливает и цикл «Запустить сейчас»."""
        try:
            while True:
                try:
                    await self._tick()
                except Exception:  # тик не должен остановить планировщик
                    log.exception("автоматизация: тик")
                await asyncio.sleep(self._tick_s)
        finally:
            if self._task is not None:
                self._task.cancel()

    async def _tick(self) -> None:
        if self.busy():
            return
        s, now = self.settings(), self._clock()
        last = next(iter(self._store.cycles(limit=1)), None)
        started = datetime.fromisoformat(last["started"]) if last else None
        nxt = next_run_at(s, paused=self.paused(), last_started=started, now=now)
        if nxt is not None and now >= nxt:
            await self.cycle("schedule")

    async def cycle(self, trigger: Trigger) -> dict[str, Any]:
        async with self._lock:
            s, now = self.settings(), self._clock()
            manual = trigger == "manual"
            rec: dict[str, Any] = {
                "trigger": trigger,
                "started": _iso(now),
                "finished": None,
                "synced": 0,
                "sources": [],
                "new_dialogs": 0,
                "queued": 0,
                "evaluated": 0,
                "errors": [],
                "cost": 0.0,
                "skipped": None,
                "after": {},
                "alerts": [],
            }
            self._current = rec
            try:
                before = {d.id for d in self._store.list_dialogs()}
                if s.sync.enabled:
                    await self._sync(s, rec, now, manual)
                new = [d.id for d in self._store.list_dialogs() if d.id not in before]
                rec["new_dialogs"] = len(new)
                batch: list[str] = []
                if s.evaluate.enabled and (manual or s.evaluate.on_new_dialogs):
                    batch = await self._evaluate(s, rec, now, manual)
                await self._after(s, rec, batch + [i for i in new if i not in batch])
            except Exception as exc:  # сбой цикла — в журнал, запись цикла и алерт, не наружу
                log.exception("автоматизация: цикл упал")
                rec["errors"].append(f"цикл: {exc}")
                basis = {"started": rec["started"], "error": str(exc)}
                self._alert(
                    rec, "automation.cycle_failed", "Цикл автоматизации упал", "cycle", rec["started"], basis
                )
            finally:
                self._phase, self._current = None, None
                rec["finished"] = _iso(self._clock())
                rec["id"] = self._store.add_cycle(rec)
            return rec

    async def _sync(self, s: AutomationSettings, rec: dict[str, Any], now: datetime, manual: bool) -> None:
        last = {} if manual else self._last_sync
        for sid in due_sources(s.sync.sources, self._ports.sources(), last, s.sync.every_min, now):
            self._phase = "syncing"
            out = await self._ports.sync(sid)
            self._last_sync[sid] = now
            row = {
                "id": sid,
                "added": out.get("added", 0),
                "skipped": out.get("skipped", 0),
                "error": out.get("error"),
            }
            rec["synced"] += 1
            rec["sources"].append(row)
            self._ports.audit("automation.sync", "source", sid, row)
            if row["error"]:
                rec["errors"].append(f"{sid}: {row['error']}")
                day = now.date().isoformat()
                basis = {"source": sid, "error": row["error"], "at": rec["started"]}
                self._alert(
                    rec,
                    "automation.source_down",
                    f"Источник {sid} недоступен",
                    "source",
                    f"{sid} {day}",
                    basis,
                )

    async def _evaluate(
        self, s: AutomationSettings, rec: dict[str, Any], now: datetime, manual: bool
    ) -> list[str]:
        ev = s.evaluate
        t = totals(self._store.cycles(since=_iso(now - timedelta(days=1))), now, budget=ev.daily_budget_usd)
        n, why = allowance(
            ev, now, spent_today=t["cost_usd"], evaluated_last_hour=t["last_hour"], quiet=not manual
        )
        if why == "budget_reached":
            self._budget_alert(rec, ev.daily_budget_usd, t["cost_usd"], now)
        if why is not None:
            rec["skipped"] = why
            return []
        batch = self.queue(s)[:n]
        if not batch:
            return []
        self._phase = "evaluating"
        left = ev.daily_budget_usd - t["cost_usd"]
        try:
            out = await self._ports.evaluate(batch, ev.priority, lambda cost: cost >= left or self.paused())
        except Conflict:  # идёт ручной запуск: пачка подождёт следующего цикла
            rec["skipped"] = "busy"
            return []
        rec.update(queued=len(batch), evaluated=out["evaluated"], cost=round(out["cost"], 6))
        rec["errors"].extend(out["errors"])
        details = {
            "dialogs": batch,
            "priority": ev.priority,
            "evaluated": out["evaluated"],
            "cost": rec["cost"],
        }
        self._ports.audit("automation.evaluate", "dialogs", ",".join(batch), details)
        if t["cost_usd"] + out["cost"] >= ev.daily_budget_usd:
            self._budget_alert(rec, ev.daily_budget_usd, t["cost_usd"] + out["cost"], now)
        return batch

    async def _after(self, s: AutomationSettings, rec: dict[str, Any], ids: list[str]) -> None:
        for name, on in s.after.model_dump().items():
            if not on:
                continue
            step = self._ports.steps.get(name)
            if step is None:
                rec["after"][name] = "недоступно"
                continue
            try:
                await step(ids)
            except Exception as exc:  # шаг после оценки не отменяет цикл
                rec["after"][name] = f"ошибка: {exc}"
                rec["errors"].append(f"{name}: {exc}")
            else:
                rec["after"][name] = "ok"
                self._ports.audit("automation.after", "step", name, {"dialogs": ids})

    def _budget_alert(self, rec: dict[str, Any], budget: float, spent: float, now: datetime) -> None:
        day = now.astimezone(ASTANA).date().isoformat()
        if self._budget_day == day:
            return
        self._budget_day = day
        title = f"Дневной бюджет автоматизации исчерпан: {spent:.2f} из {budget:.2f} USD"
        basis = {"day": day, "budget_usd": budget, "spent_usd": round(spent, 6)}
        self._alert(rec, "automation.budget", title, "automation", day, basis)

    def _alert(
        self,
        rec: dict[str, Any],
        rule_id: str,
        title: str,
        target_type: str,
        target_id: str,
        basis: dict[str, Any],
    ) -> None:
        """Форма срабатывания алертов (#87): {rule_id, severity, title, target_type, target_id, basis}."""
        hit = {
            "rule_id": rule_id,
            "severity": "warning",
            "title": title,
            "target_type": target_type,
            "target_id": target_id,
            "basis": basis,
        }
        rec["alerts"].append(hit)
        log.warning("автоматизация: %s", title)
        try:
            self._ports.notify(hit)
        except Exception:  # алерт не должен уронить цикл
            log.exception("автоматизация: алерт не записан")
        self._ports.audit("automation.alert", target_type, target_id, {"rule_id": rule_id, "title": title})


COLUMNS = (
    "id",
    "trigger",
    "started",
    "finished",
    "synced",
    "new_dialogs",
    "queued",
    "evaluated",
    "cost",
    "skipped",
)


def cycles_csv(rows: list[dict[str, Any]]) -> str:
    """Журнал циклов для Excel (→ рендерер отчётов, когда он в main)."""
    body = [
        [str(r.get(c) if r.get(c) is not None else "") for c in COLUMNS] + ["; ".join(r["errors"])]
        for r in rows
    ]
    return excel_csv([[*COLUMNS, "errors"], *body])
