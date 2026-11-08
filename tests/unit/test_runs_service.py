"""Runs: plan of pairs without a current result, ordered workers, cancel and resume, honest progress."""

import asyncio
import itertools
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Checklist, Criterion, CriterionResult, Dialog
from cqa.domain.review import fingerprint
from cqa.services.errors import Conflict, NotFound
from cqa.services.runs import Runner, eta_seconds, plan_run
from cqa.services.state import current_results
from fakes import FakeEvaluator, prototype_checklist, prototype_dialogs

CHECKLIST = prototype_checklist()
DIALOGS = {d.id: d for d in prototype_dialogs()}


def _current(store: Store) -> dict[str, dict[str, CriterionResult]]:
    return current_results(store, CHECKLIST, store.list_dialogs())


def _clock() -> Callable[[], float]:
    return itertools.count(100.0, 0.5).__next__  # every reading is half a second later


async def _execute(store: Store, evaluator: FakeEvaluator, dialogs: list[str] | None = None) -> int:
    plan = plan_run(store, CHECKLIST, dialogs, None)
    run_id = store.add_run(sum(len(cs) for _, cs in plan), 100.0)
    await Runner(store, evaluator, parallel=1, clock=_clock()).execute(run_id, CHECKLIST, plan)
    return run_id


def _ids(plan: list[tuple[Dialog, list]]) -> list[tuple[str, list[str]]]:
    return [(d.id, [c.id for c in cs]) for d, cs in plan]


ALL = [c.id for c in CHECKLIST.criteria]


@pytest.mark.parametrize(
    ("done", "total", "elapsed", "eta"), [(4, 16, 10.0, 30), (0, 16, 5.0, None), (16, 16, 9.0, 0)]
)
def test_eta_extrapolates_elapsed_time_per_done_pair(done: int, total: int, elapsed: float, eta: int) -> None:
    assert eta_seconds(done, total, elapsed) == eta


def test_plan_takes_every_criterion_of_dialogs_without_results(store: Store) -> None:
    assert _ids(plan_run(store, CHECKLIST, None, None)) == [("call-024", ALL), ("p1-ru-003", ALL)]


def test_plan_skips_pairs_with_a_current_result(store: Store) -> None:
    for c in CHECKLIST.criteria:
        store.add_result(
            "call-024", c.id, 3, fingerprint(CHECKLIST, c, "call"), DIALOGS["call-024"].res[c.id]
        )
    assert _ids(plan_run(store, CHECKLIST, None, None)) == [("p1-ru-003", ALL)]


def test_plan_ignores_results_of_another_meaning(store: Store) -> None:
    store.add_result("call-024", "04", 3, "0000000000000000", DIALOGS["call-024"].res["04"])
    assert _ids(plan_run(store, CHECKLIST, ["call-024"], ["04"])) == [("call-024", ["04"])]


def test_changed_call_addendum_replans_only_call_dialogs(store: Store) -> None:
    for d in store.list_dialogs():
        for c in CHECKLIST.criteria:
            store.add_result(d.id, c.id, 3, fingerprint(CHECKLIST, c, d.ch), CriterionResult(a="yes"))
    criteria = [
        c.model_copy(update={"call": "Новое уточнение"}) if c.id == "01" else c for c in CHECKLIST.criteria
    ]
    changed = CHECKLIST.model_copy(update={"criteria": criteria})
    assert _ids(plan_run(store, changed, None, None)) == [("call-024", ["01"])]


async def test_execute_saves_call_results_under_the_call_fingerprint(store: Store) -> None:
    criteria = [c.model_copy(update={"call": "Уточнение"}) if c.id == "01" else c for c in CHECKLIST.criteria]
    changed = CHECKLIST.model_copy(update={"criteria": criteria})
    plan = plan_run(store, changed, None, ["01"])
    await Runner(store, FakeEvaluator(), parallel=1).execute(store.add_run(2, 100.0), changed, plan)
    assert sorted(current_results(store, changed, store.list_dialogs())) == ["call-024", "p1-ru-003"]
    assert plan_run(store, changed, None, ["01"]) == []


def test_plan_limits_criteria_to_the_argument(store: Store) -> None:
    assert _ids(plan_run(store, CHECKLIST, None, ["04"])) == [("call-024", ["04"]), ("p1-ru-003", ["04"])]


def test_plan_follows_the_order_of_the_dialogs_argument(store: Store) -> None:
    plan = plan_run(store, CHECKLIST, ["p1-ru-003", "call-024"], None)
    assert [d.id for d, _ in plan] == ["p1-ru-003", "call-024"]


def test_plan_does_not_repeat_a_dialog_listed_twice(store: Store) -> None:
    assert [d.id for d, _ in plan_run(store, CHECKLIST, ["call-024", "call-024"], None)] == ["call-024"]


def test_plan_does_not_check_unknown_ids(store: Store) -> None:
    assert _ids(plan_run(store, CHECKLIST, ["nope", "call-024"], ["99", "04"])) == [("call-024", ["04"])]


async def test_execute_saves_results_with_version_and_fingerprint(
    store: Store, conn: sqlite3.Connection
) -> None:
    await _execute(store, FakeEvaluator())
    current = _current(store)
    assert {d: sorted(r) for d, r in current.items()} == {"call-024": ALL, "p1-ru-003": ALL}
    assert current["call-024"]["04"].a == DIALOGS["call-024"].res["04"].a
    versions = conn.execute("SELECT DISTINCT version FROM results").fetchall()
    assert [row[0] for row in versions] == [3]


async def test_execute_counts_progress_and_finishes_done(store: Store) -> None:
    run = store.get_run(await _execute(store, FakeEvaluator()))
    assert run is not None
    assert (run.done, run.calls, run.errors, run.status) == (16, 16, [], "done")
    assert run.cost == pytest.approx(0.016)
    assert run.finished is not None


async def test_execute_writes_dialog_cost_with_second_opinion(store: Store) -> None:
    run_id = await _execute(store, FakeEvaluator(verifier_calls=1, verifier_usd=0.0002))
    dialog = store.get_dialog("call-024")
    assert dialog is not None and dialog.cost is not None
    assert dialog.cost.model_dump() == {
        "calls": 8,
        "verifier_calls": 1,
        "usd": pytest.approx(0.0082),
        "ms": 500,
    }
    run = store.get_run(run_id)
    assert run is not None and run.cost == pytest.approx(0.0164)


async def test_one_worker_takes_dialogs_in_plan_order(store: Store, conn: sqlite3.Connection) -> None:
    evaluator = FakeEvaluator()
    await _execute(store, evaluator, ["p1-ru-003", "call-024"])
    assert evaluator.order == ["p1-ru-003", "call-024"]
    first = conn.execute("SELECT dialog_id FROM results ORDER BY id LIMIT 1").fetchone()
    assert first[0] == "p1-ru-003"


async def test_workers_start_a_dialog_only_when_a_place_is_free(store: Store) -> None:
    store.add_dialogs([DIALOGS["p1-ru-025"]], {})
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    plan = plan_run(store, CHECKLIST, ["p1-ru-025", "p1-ru-003", "call-024"], None)
    run_id = store.add_run(24, 100.0)
    task = asyncio.create_task(Runner(store, evaluator, parallel=2).execute(run_id, CHECKLIST, plan))
    for _ in range(5):
        await asyncio.sleep(0)
    assert evaluator.order == ["p1-ru-025", "p1-ru-003"]
    gate.set()
    await task
    assert evaluator.order == ["p1-ru-025", "p1-ru-003", "call-024"]


async def test_failed_dialog_is_an_error_and_does_not_stop_the_rest(store: Store) -> None:
    run = store.get_run(await _execute(store, FakeEvaluator(fail_on={"p1-ru-003"})))
    assert run is not None
    assert (run.done, run.errors, run.status) == (16, ["p1-ru-003: timeout"], "done")
    assert sorted(_current(store)) == ["call-024"]
    assert store.get_dialog("p1-ru-003").cost is None  # type: ignore[union-attr]


async def test_eta_does_not_extrapolate_from_a_dialog_that_failed_at_once(store: Store) -> None:
    # live: a call refused without CQA_ALLOW_REAL_DATA counts as done in 0 s and made ETA climb to minutes
    gate = asyncio.Event()
    runner = Runner(store, FakeEvaluator(fail_on={"call-024"}, gate=gate), parallel=1, clock=_clock())
    run_id = runner.start(["call-024", "p1-ru-003"], None)
    for _ in range(5):
        await asyncio.sleep(0)
    progress = runner.progress(run_id)
    assert (progress["done"], progress["eta_s"]) == (8, None)
    gate.set()
    await _drain(runner)
    assert runner.progress(run_id)["eta_s"] == 0


async def test_missing_answer_is_an_error_and_waits_for_evaluation(store: Store) -> None:
    run = store.get_run(await _execute(store, FakeEvaluator(skip={"04"})))
    assert run is not None
    assert run.errors == [
        "call-024/04: нет ответа модели, ждёт оценки",
        "p1-ru-003/04: нет ответа модели, ждёт оценки",
    ]
    assert run.done == 16
    assert "04" not in _current(store)["call-024"]


async def _drain(runner: Runner) -> None:
    await asyncio.gather(*runner._tasks)


async def _first_in_flight(evaluator: FakeEvaluator) -> None:
    for _ in range(100):
        if evaluator.order:
            return
        await asyncio.sleep(0)
    raise AssertionError("evaluate was never called")


async def test_start_rejects_unknown_dialogs(store: Store) -> None:
    with pytest.raises(NotFound, match="^Диалоги не найдены: nope, nope2$"):
        Runner(store, FakeEvaluator(), parallel=1).start(["call-024", "nope", "nope2"], None)


async def test_start_rejects_unknown_criteria(store: Store) -> None:
    with pytest.raises(NotFound, match="^Критериев нет в чек-листе v3: 99$"):
        Runner(store, FakeEvaluator(), parallel=1).start(None, ["04", "99"])


async def test_start_with_nothing_to_do_finishes_at_once_without_a_task(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(), parallel=1)
    runner.start(None, None)
    await _drain(runner)
    evaluator = FakeEvaluator()
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(None, None)
    run = store.get_run(run_id)
    assert run is not None and (run.total, run.status) == (0, "done")
    assert runner._tasks == set()
    assert evaluator.calls == 0


async def test_second_start_while_a_run_is_active_is_a_conflict(store: Store) -> None:
    gate = asyncio.Event()
    runner = Runner(store, FakeEvaluator(gate=gate), parallel=1)
    run_id = runner.start(None, None)
    assert len(runner._tasks) == 1
    with pytest.raises(Conflict, match=f"^Запуск {run_id} ещё идёт$"):
        runner.start(None, None)
    gate.set()
    await _drain(runner)
    assert runner._tasks == set()
    run = store.get_run(runner.start(None, ["04"]))
    assert run is not None and (run.total, run.status) == (0, "done")


async def test_started_run_evaluates_the_plan_in_the_background(store: Store) -> None:
    evaluator = FakeEvaluator()
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(["p1-ru-003", "call-024"], None)
    await _drain(runner)
    run = store.get_run(run_id)
    assert run is not None and (run.total, run.done, run.status) == (16, 16, "done")
    assert evaluator.order == ["p1-ru-003", "call-024"]


async def test_cancel_lets_the_dialog_in_flight_finish_and_starts_no_new_one(store: Store) -> None:
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(None, None)
    await _first_in_flight(evaluator)
    assert runner.cancel(run_id) == {"status": "cancelled"}
    gate.set()
    await _drain(runner)
    assert evaluator.order == ["call-024"]
    assert sorted(_current(store)) == ["call-024"]
    progress = runner.progress(run_id)
    assert (progress["status"], progress["done"], progress["total"], progress["eta_s"]) == (
        "cancelled",
        8,
        16,
        None,
    )


async def test_new_start_after_cancel_resumes_where_the_run_stopped(store: Store) -> None:
    gate = asyncio.Event()
    first = FakeEvaluator(gate=gate)
    runner = Runner(store, first, parallel=1)
    run_id = runner.start(None, None)
    await _first_in_flight(first)
    runner.cancel(run_id)
    gate.set()
    await _drain(runner)
    evaluator = FakeEvaluator()
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(None, None)
    await _drain(runner)
    assert evaluator.order == ["p1-ru-003"]
    assert runner.progress(run_id)["total"] == 8


async def test_cancel_of_a_finished_or_unknown_run_is_refused(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(), parallel=1)
    run_id = runner.start(None, None)
    await _drain(runner)
    with pytest.raises(Conflict, match=f"^Запуск {run_id} уже завершён: done$"):
        runner.cancel(run_id)
    with pytest.raises(NotFound, match="^Запуск 999 не найден$"):
        runner.cancel(999)
    with pytest.raises(NotFound, match="^Запуск 999 не найден$"):
        runner.progress(999)


def test_progress_of_a_running_run_extrapolates_eta_from_the_clock(store: Store) -> None:
    run_id = store.add_run(16, 100.0)
    store.record_progress(run_id, 4, 0.004, 4, ["p1-ru-003: timeout"])
    runner = Runner(store, FakeEvaluator(), parallel=1, clock=lambda: 110.0)
    assert runner.progress(run_id) == {
        "done": 4,
        "total": 16,
        "cost": pytest.approx(0.004),
        "calls": 4,
        "eta_s": 30,
        "errors": ["p1-ru-003: timeout"],
        "status": "running",
    }


async def test_progress_of_a_finished_run(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(), parallel=1)
    run_id = runner.start(None, None)
    await _drain(runner)
    assert runner.progress(run_id) == {
        "done": 16,
        "total": 16,
        "cost": pytest.approx(0.016),
        "calls": 16,
        "eta_s": 0,
        "errors": [],
        "status": "done",
    }


def test_cancel_of_a_running_row_without_a_task_marks_it_cancelled(store: Store) -> None:
    run_id = store.add_run(16, 100.0)
    runner = Runner(store, FakeEvaluator(), parallel=1)
    assert runner.cancel(run_id) == {"status": "cancelled"}
    assert runner.progress(run_id)["status"] == "cancelled"


class SilentTimeout(FakeEvaluator):
    async def evaluate(self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]) -> Any:
        raise TimeoutError  # asyncio.wait_for raises it without a message


async def test_error_without_a_message_names_the_exception(store: Store) -> None:
    run = store.get_run(await _execute(store, SilentTimeout(), ["call-024"]))
    assert run is not None and run.errors == ["call-024: TimeoutError"]


async def test_use_swaps_the_evaluator_for_the_next_run(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(), parallel=1, clock=_clock())
    other = FakeEvaluator()
    runner.use(other)
    assert runner._evaluator is other


async def test_use_during_a_run_is_a_conflict(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(), parallel=1, clock=_clock())
    runner.start(["call-024"], None)
    with pytest.raises(Conflict, match="идёт"):
        runner.use(FakeEvaluator())
    runner.cancel(runner._active or 0)


def _announced() -> tuple[list[dict[str, Any]], Callable[[dict[str, Any]], Any]]:
    events: list[dict[str, Any]] = []

    async def on_finish(event: dict[str, Any]) -> None:
        events.append(event)

    return events, on_finish


async def test_finished_run_is_announced_with_counts_and_requested_dialogs(store: Store) -> None:
    events, on_finish = _announced()
    runner = Runner(store, FakeEvaluator(fail_on={"p1-ru-003"}), parallel=1, on_finish=on_finish)
    run_id = runner.start(["call-024", "p1-ru-003"], None)
    await _drain(runner)
    assert events == [
        {
            "event": "run.finished",
            "run_id": run_id,
            "status": "done",
            "done": 16,
            "total": 16,
            "errors": ["p1-ru-003: timeout"],
            "dialog_ids": ["call-024", "p1-ru-003"],
        }
    ]


async def test_run_with_nothing_to_do_is_announced_too(store: Store) -> None:
    events, on_finish = _announced()
    runner = Runner(store, FakeEvaluator(), parallel=1, on_finish=on_finish)
    runner.start(["call-024"], None)
    await _drain(runner)
    run_id = runner.start(["call-024"], None)
    await _drain(runner)
    assert [(e["run_id"], e["total"], e["dialog_ids"]) for e in events][-1] == (run_id, 0, ["call-024"])


async def test_ensure_idle_refuses_while_a_run_is_active(store: Store) -> None:
    gate = asyncio.Event()
    runner = Runner(store, FakeEvaluator(gate=gate), parallel=1)
    runner.ensure_idle()
    run_id = runner.start(None, None)
    with pytest.raises(Conflict, match=f"^Запуск {run_id} ещё идёт$"):
        runner.ensure_idle()
    gate.set()
    await _drain(runner)


async def test_conflict_names_the_active_run_with_its_progress(store: Store) -> None:
    gate = asyncio.Event()
    runner = Runner(store, FakeEvaluator(gate=gate), parallel=1, clock=_clock())
    run_id = runner.start(None, None)
    with pytest.raises(Conflict) as err:
        runner.ensure_idle()
    assert err.value.extra == {"run_id": run_id, "done": 0, "total": 16, "eta_s": None}
    gate.set()
    await _drain(runner)


async def test_runner_tells_the_dialogs_of_a_run_and_the_ones_in_flight(store: Store) -> None:
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(["p1-ru-003", "call-024"], None)
    await _first_in_flight(evaluator)
    assert (runner.dialog_ids(run_id), runner.in_flight()) == (["p1-ru-003", "call-024"], {"p1-ru-003"})
    gate.set()
    await _drain(runner)
    assert (runner.in_flight(), runner.dialog_ids(run_id + 1)) == (set(), None)
