"""Цикл автоматизации на подделках: синхронизация → очередь → оценка → шаги после, без двух циклов сразу."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Dialog
from cqa.domain.review import ASTANA
from cqa.services.automation import Automation, Ports
from cqa.services.errors import Conflict
from fakes import prototype_dialogs

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=ASTANA)
ON = {"enabled": True, "evaluate": {"batch_size": 5, "daily_budget_usd": 1.0}}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Fake:
    """Порты: источник «org», оценка пачкой по 0,1 USD за диалог, журнал действий и алерты в списках."""

    def __init__(self, store: Store, *, new: list[Dialog] | None = None) -> None:
        self.store = store
        self.new = new or []
        self.synced: list[str] = []
        self.batches: list[list[str]] = []
        self.audited: list[tuple[str, str, str]] = []
        self.alerts: list[dict[str, Any]] = []
        self.steps: list[tuple[str, list[str]]] = []
        self.sync_error: str | None = None
        self.sync_raises: Exception | None = None
        self.gate: asyncio.Event | None = None
        self.stop_seen: list[bool] = []

    async def sync(self, source_id: str) -> Mapping[str, Any]:
        self.synced.append(source_id)
        if self.sync_raises:
            raise self.sync_raises
        added, skipped = self.store.add_dialogs(self.new, {})
        return {"added": added, "skipped": skipped, "error": self.sync_error}

    async def evaluate(
        self, ids: list[str], priority: str, stop: Callable[[float], bool]
    ) -> Mapping[str, Any]:
        self.batches.append(ids)
        if self.gate:
            await self.gate.wait()
        self.stop_seen.append(stop(0.1 * len(ids)))
        return {"evaluated": len(ids), "cost": 0.1 * len(ids), "errors": []}

    def ports(self, **over: Any) -> Ports:
        async def prosody(ids: list[str]) -> None:
            self.steps.append(("prosody_for_calls", ids))

        return Ports(
            sources=lambda: ["org"],
            sync=self.sync,
            evaluate=self.evaluate,
            source_of=lambda d: "org",
            notify=self.alerts.append,
            audit=lambda action, kind, target, details: self.audited.append((action, kind, target)),
            steps={"prosody_for_calls": prosody},
            **over,
        )


def _auto(
    store: Store, fake: Fake, clock: Clock | None = None, settings: Any = ON, **over: Any
) -> Automation:
    auto = Automation(store, fake.ports(**over), clock=clock or Clock(), tick_s=0.01)
    _, errors = auto.put(settings)
    assert errors == []
    return auto


async def test_cycle_syncs_and_sends_the_newest_unscored_dialogs_to_the_model(store: Store) -> None:
    new = [d for d in prototype_dialogs() if d.id == "p1-kz-015"]
    fake = Fake(store, new=new)
    rec = await _auto(store, fake).cycle("schedule")
    assert fake.synced == ["org"]
    assert fake.batches == [["p1-kz-015", "p1-ru-003", "call-024"]]
    assert (rec["synced"], rec["new_dialogs"], rec["queued"], rec["evaluated"]) == (1, 1, 3, 3)
    assert rec["cost"] == pytest.approx(0.3)
    assert ("automation.sync", "source", "org") in fake.audited
    assert ("automation.evaluate", "dialogs", "p1-kz-015,p1-ru-003,call-024") in fake.audited


async def test_budget_reached_stops_evaluation_and_raises_one_alert_a_day(store: Store) -> None:
    fake = Fake(store)
    auto = _auto(store, fake, settings={"enabled": True, "evaluate": {"daily_budget_usd": 0.15}})
    first = await auto.cycle("schedule")  # 2 диалога по 0,1 — бюджет 0,15 превышен
    assert first["evaluated"] == 2
    second = await auto.cycle("schedule")
    assert second["skipped"] == "budget_reached"
    assert len(fake.batches) == 1
    assert [a["rule_id"] for a in fake.alerts] == ["automation.budget"]
    assert fake.alerts[0]["basis"]["budget_usd"] == 0.15
    assert auto.status()["state"] == "budget_reached"
    assert auto.status()["today"] == {"dialogs_evaluated": 2, "cost_usd": 0.2, "budget_left": 0.0}


async def test_never_two_cycles_at_once(store: Store) -> None:
    fake = Fake(store)
    fake.gate = asyncio.Event()
    auto = _auto(store, fake)
    auto.run_now()
    await asyncio.sleep(0.01)
    assert auto.status()["state"] == "evaluating"
    with pytest.raises(Conflict, match="уже идёт"):
        auto.run_now()
    loop = asyncio.create_task(auto.run())
    await asyncio.sleep(0.05)  # тики планировщика видят идущий цикл и ждут
    fake.gate.set()
    await asyncio.sleep(0.02)
    loop.cancel()
    assert len(fake.batches) == 1


async def test_default_off_loop_never_syncs_or_evaluates(store: Store) -> None:
    fake = Fake(store)
    auto = Automation(store, fake.ports(), clock=Clock(), tick_s=0.01)
    loop = asyncio.create_task(auto.run())
    await asyncio.sleep(0.05)
    loop.cancel()
    assert (fake.synced, fake.batches, auto.cycles(10)) == ([], [], [])
    assert auto.status()["state"] == "off"
    assert auto.owns_sync() is False
