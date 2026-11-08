"""Batch jobs: splitting, priority queue, pause/resume/cancel/retry, failures, ETA, restart."""

import asyncio
import sqlite3
from datetime import date

import pytest

from cqa.adapters.batches import BatchStore, JobRow
from cqa.adapters.store import Store
from cqa.services.batches import RESTART_NOTE, Batches, next_job, pace
from cqa.services.runs import Runner
from fakes import FakeEvaluator, prototype_dialogs

FIVE = ["call-024", "p1-ru-003", "p1-ru-022", "p1-kz-015", "p1-en-008"]


@pytest.fixture
def full(store: Store) -> Store:
    """Five dialogs: the two of `store` plus three more from the prototype."""
    store.add_dialogs([d for d in prototype_dialogs() if d.id in FIVE[2:]], {})
    return store


def _batches(store: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator, **kw: object) -> Batches:
    runner = Runner(store, evaluator, parallel=2)
    return Batches(store, BatchStore(conn), runner, poll_s=0, **kw)  # type: ignore[arg-type]


async def _drain(batches: Batches) -> int:
    steps = 0
    while await batches.step():
        steps += 1
    return steps


def _job(id_: int, priority: str, status: str = "queued") -> JobRow:
    return JobRow(id=id_, priority=priority, status=status, batch_size=20, force=False, note=None, created=0)  # type: ignore[arg-type]


def test_next_job_takes_high_priority_first_then_fifo() -> None:
    jobs = [_job(1, "low"), _job(2, "normal"), _job(3, "high"), _job(4, "high"), _job(5, "high", "paused")]
    assert next_job(jobs).id == 3  # type: ignore[union-attr]
    assert next_job(jobs[:2]).id == 2  # type: ignore[union-attr]
    assert next_job([_job(1, "normal", "done"), _job(2, "high", "cancelled")]) is None


@pytest.mark.parametrize(
    ("recent", "remaining", "expected"),
    [
        ([], 10, (None, None, "нет завершённых батчей")),
        ([(20, 60.0)], 40, (20.0, 120, "по скорости последнего батча")),
        ([(5, 600.0), (10, 30.0), (10, 30.0), (10, 60.0)], 15, (15.0, 60, "по скорости последних 3 батчей")),
        ([(10, 30.0)], 0, (20.0, 0, "по скорости последнего батча")),
    ],
)
def test_pace_uses_the_last_three_finished_batches(
    recent: list[tuple[int, float]], remaining: int, expected: tuple[object, ...]
) -> None:
    assert pace(recent, remaining) == expected


async def test_job_is_split_into_batches_and_every_batch_runs(
    full: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> None:
    batches = _batches(full, conn, evaluator)
    job = batches.create(FIVE, None, batch_size=2, priority="normal", force=False)
    assert ([b["n"] for b in job["batches"]], job["status"], job["pending"]) == ([2, 2, 1], "queued", 5)
    assert await _drain(batches) == 3
    view = batches.view(job["id"])
    assert (view["status"], view["done"], view["errors"], view["pending"]) == ("done", 5, 0, 0)
    assert [(b["n"], b["done"], b["errors"]) for b in view["batches"]] == [(2, 2, 0), (2, 2, 0), (1, 1, 0)]
    assert all(b["started"] and b["finished"] and b["cost"] > 0 for b in view["batches"])
    assert view["cost"] == pytest.approx(sum(b["cost"] for b in view["batches"]))
    assert evaluator.order == FIVE


async def test_failed_dialog_is_recorded_and_the_job_continues_then_retry_runs_only_it(
    full: Store, conn: sqlite3.Connection
) -> None:
    evaluator = FakeEvaluator(fail_on={"p1-ru-003"})
    batches = _batches(full, conn, evaluator)
    job_id = batches.create(FIVE, None, batch_size=2, priority="normal", force=False)["id"]
    await _drain(batches)
    view = batches.view(job_id)
    assert (view["status"], view["done"], view["errors"]) == ("done", 4, 1)
    assert view["failed"] == [{"dialog": "p1-ru-003", "error": "timeout"}]
    assert [b["errors"] for b in view["batches"]] == [1, 0, 0]

    evaluator.fail_on.clear()
    evaluator.order.clear()
    assert batches.act(job_id, "retry")["status"] == "queued"
    await _drain(batches)
    view = batches.view(job_id)
    assert (view["status"], view["done"], view["errors"], view["failed"]) == ("done", 5, 0, [])
    assert evaluator.order == ["p1-ru-003"]


async def test_high_priority_job_overtakes_a_normal_one_at_the_batch_boundary(
    full: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> None:
    batches = _batches(full, conn, evaluator)
    normal = batches.create(FIVE[:4], None, batch_size=2, priority="normal", force=False)["id"]
    await batches.step()
    high = batches.create([FIVE[4]], None, batch_size=2, priority="high", force=False)["id"]
    await batches.step()
    assert evaluator.order == [*FIVE[:2], FIVE[4]]
    assert (batches.view(high)["status"], batches.view(normal)["status"]) == ("done", "queued")
    await _drain(batches)
    assert batches.view(normal)["status"] == "done"


async def test_paused_job_waits_and_resume_continues(
    full: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> None:
    batches = _batches(full, conn, evaluator)
    job_id = batches.create(FIVE[:4], None, batch_size=2, priority="normal", force=False)["id"]
    await batches.step()
    assert batches.act(job_id, "pause")["status"] == "paused"
    assert await batches.step() is False
    assert batches.view(job_id)["pending"] == 2
    assert batches.act(job_id, "resume")["status"] == "queued"
    await _drain(batches)
    assert batches.view(job_id)["status"] == "done"


async def test_worker_waits_for_a_manual_run_instead_of_breaking_the_one_run_rule(
    store: Store, conn: sqlite3.Connection
) -> None:
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    batches = _batches(store, conn, evaluator)
    manual = batches._runner.start(["call-024"], None)
    job_id = batches.create(["p1-ru-003"], None, batch_size=1, priority="high", force=False)["id"]
    step = asyncio.create_task(batches.step())
    for _ in range(5):
        await asyncio.sleep(0)
    assert batches.view(job_id)["batches"][0]["run_id"] is None
    gate.set()
    await step
    view = batches.view(job_id)
    assert (view["status"], view["batches"][0]["run_id"]) == ("done", manual + 1)


def test_filter_selects_unscored_dialogs_by_channel_language_and_date(
    full: Store, conn: sqlite3.Connection
) -> None:
    batches = _batches(full, conn, FakeEvaluator())
    assert batches.select({"ch": "call"}) == ["call-024"]
    assert batches.select({"lang": "KZ"}) == ["p1-kz-015"]
    assert batches.select({"since": date(2026, 11, 8)}) == []
    assert batches.select({"since": date(2026, 11, 7)}) == FIVE
    assert batches.select({}) == FIVE
    assert batches.select({"source_id": "nope"}) == []  # поля нет у диалога — фильтр ничего не находит


async def test_restart_pauses_unfinished_jobs_with_a_note(
    full: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> None:
    batches = _batches(full, conn, evaluator)
    running = batches.create(FIVE[:4], None, batch_size=2, priority="normal", force=False)["id"]
    await batches.step()
    queued = batches.create([FIVE[4]], None, batch_size=2, priority="low", force=False)["id"]

    restarted = _batches(full, conn, evaluator)  # новый процесс на той же базе
    restarted.recover()
    for job_id in (running, queued):
        view = restarted.view(job_id)
        assert (view["status"], view["note"]) == ("paused", RESTART_NOTE)
    assert await restarted.step() is False
    restarted.act(running, "resume")
    assert restarted.view(running)["note"] is None
    await _drain(restarted)
    assert (restarted.view(running)["status"], restarted.view(queued)["status"]) == ("done", "paused")
