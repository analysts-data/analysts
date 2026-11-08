"""Runs: plan of pairs without a current result, ordered workers, cancel and resume, honest progress."""

import asyncio
import itertools
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Appeal, Checklist, Criterion, CriterionResult, Dialog
from cqa.domain.review import fingerprint
from cqa.services.answers import MANUAL
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.runs import Runner, compare_runs, eta_seconds, list_runs, plan_rerun, plan_run
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


async def test_interrupted_run_is_cancelled_not_done(store: Store) -> None:
    """Ctrl-C в scripts/results.py или остановка сервера отменяют задачу: запуск не «done»."""
    evaluator = FakeEvaluator(gate=asyncio.Event())
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(None, None)
    await _first_in_flight(evaluator)
    for task in runner._tasks:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await _drain(runner)
    progress = runner.progress(run_id)
    assert (progress["status"], progress["done"]) == ("cancelled", 0)


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
        "products": {"done": 0, "total": 0, "errors": 0, "cost": 0.0},
        "skipped": 0,
        "insufficient": 0,
        "dialogs": [],
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
        "products": {"done": 0, "total": 0, "errors": 0, "cost": 0.0},
        "skipped": 0,
        "insufficient": 0,
        "dialogs": [
            {"id": "call-024", "status": "done", "error": None, "done": 8, "total": 8, "skipped": 0},
            {"id": "p1-ru-003", "status": "done", "error": None, "done": 8, "total": 8, "skipped": 0},
        ],
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


# --- повторная проверка, запуски, сравнение ---


def _answer_all(store: Store, run_id: int | None = None) -> None:
    for d in store.list_dialogs():
        for c in CHECKLIST.criteria:
            store.add_result(
                d.id, c.id, 3, fingerprint(CHECKLIST, c, d.ch), CriterionResult(a="na"), run_id=run_id
            )


def _appeal(store: Store, dlg: str, cid: str, status: str, fp: str | None = None) -> None:
    ch = DIALOGS[dlg].ch
    criterion = next(c for c in CHECKLIST.criteria if c.id == cid)
    appeal = Appeal.model_validate(
        {"id": "", "kind": "appeal", "dlg": dlg, "cid": cid, "from": "na", "ask": "na", "by": "Оператор",
         "at": "07.11 15:10", "status": status, "comment": "Не согласен с оценкой"}
    )  # fmt: skip
    store.add_appeal(appeal, fp or fingerprint(CHECKLIST, criterion, ch))


def test_rerun_plans_pairs_that_already_have_a_current_result(store: Store) -> None:
    _answer_all(store)
    assert plan_run(store, CHECKLIST, None, None) == []
    plan, held = plan_rerun(store, CHECKLIST, None, ["01", "04"])
    assert (_ids(plan), held) == ([("call-024", ["01", "04"]), ("p1-ru-003", ["01", "04"])], {})


def test_rerun_skips_manual_answers_and_pairs_with_an_open_or_decided_appeal(store: Store) -> None:
    _answer_all(store)
    store.add_result("call-024", "01", 3, fingerprint(CHECKLIST, CHECKLIST.criteria[0], "call"),
                     CriterionResult(a="yes", model=MANUAL))  # fmt: skip
    _appeal(store, "call-024", "04", "pending")
    _appeal(store, "p1-ru-003", "04", "changed")
    _appeal(store, "p1-ru-003", "01", "closed")  # closed and other meanings do not hold the pair
    _appeal(store, "p1-ru-003", "05", "confirmed", fp="0000000000000000")

    plan, held = plan_rerun(store, CHECKLIST, None, ["01", "04", "05"])

    assert _ids(plan) == [("call-024", ["05"]), ("p1-ru-003", ["01", "05"])]
    assert held == {"call-024": 2, "p1-ru-003": 1}  # dialog -> pairs a human holds


async def test_execute_saves_the_run_id_with_every_result(store: Store) -> None:
    run_id = await _execute(store, FakeEvaluator(), ["call-024"])
    rows = store.result_rows(dialog_id="call-024")
    assert len(rows) == 8 and {r.run_id for r in rows} == {run_id}


async def test_forced_start_re_evaluates_and_reports_skipped_pairs(store: Store) -> None:
    _answer_all(store)
    _appeal(store, "call-024", "04", "pending")
    evaluator = FakeEvaluator()
    runner = Runner(store, evaluator, parallel=1, clock=_clock())

    run_id = runner.start(["call-024"], None, force=True, model="qwen3-6")
    await _drain(runner)

    run = store.get_run(run_id)
    assert run is not None
    assert (run.total, run.force, run.skipped, run.model, run.checklist_version) == (7, True, 1, "qwen3-6", 3)
    assert runner.progress(run_id)["skipped"] == 1
    assert _current(store)["call-024"]["01"].a == DIALOGS["call-024"].res["01"].a  # the newest row wins
    assert _current(store)["call-024"]["04"].a == "na"
    assert "04" not in evaluator.seen


async def test_plain_start_skips_nothing_on_purpose(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(), parallel=1)
    run_id = runner.start(["call-024"], None)
    await _drain(runner)
    assert runner.progress(run_id)["skipped"] == 0
    assert store.get_run(run_id).force is False  # type: ignore[union-attr]


def test_list_runs_shows_recent_runs_newest_first(store: Store) -> None:
    first = store.add_run(16, 0.0, model="qwen3-6", checklist_version=3)
    store.record_progress(first, 16, 0.016, 16, ["p1-ru-003: timeout"])
    store.finish_run(first, 9.0, "done")
    second = store.add_run(8, 60.0, model="jev-latest", checklist_version=3, force=True, skipped=1)

    assert list_runs(store) == [
        {"id": second, "created": "1970-01-01T00:01:00+00:00", "status": "running", "model": "jev-latest",
         "checklist_version": 3, "total": 8, "done": 0, "cost": 0.0, "errors_count": 0, "force": True,
         "skipped": 1, "apply": "replace", "override": None},
        {"id": first, "created": "1970-01-01T00:00:00+00:00", "status": "done", "model": "qwen3-6",
         "checklist_version": 3, "total": 16, "done": 16, "cost": pytest.approx(0.016), "errors_count": 1,
         "force": False, "skipped": 0, "apply": "replace", "override": None},
    ]  # fmt: skip


def test_compare_runs_takes_the_latest_answer_of_each_run(store: Store) -> None:
    a = store.add_run(2, 0.0)
    b = store.add_run(2, 1.0)
    fp = fingerprint(CHECKLIST, CHECKLIST.criteria[0], "call")
    store.add_result("call-024", "01", 3, fp, CriterionResult(a="no"), run_id=a)
    store.add_result("call-024", "01", 3, fp, CriterionResult(a="yes"), run_id=a)  # restored copy
    store.add_result("call-024", "01", 3, fp, CriterionResult(a="yes"), run_id=b)
    store.add_result("call-024", "01", 3, fp, CriterionResult(a="no"))  # manual: no run

    got = compare_runs(store, a, b)

    assert (got["a"], got["b"], got["pairs"], got["agree"], got["diffs"]) == (a, b, 1, 1.0, [])


def test_compare_with_an_unknown_run_is_not_found(store: Store) -> None:
    a = store.add_run(0, 0.0)
    with pytest.raises(NotFound, match="^Запуск 999 не найден$"):
        compare_runs(store, a, 999)


# --- статусы диалогов запуска, подтверждение большого перезапуска ---


def _statuses(runner: Runner, run_id: int) -> list[tuple[str, str, int, int]]:
    return [(d["id"], d["status"], d["done"], d["total"]) for d in runner.progress(run_id)["dialogs"]]


async def test_progress_tells_each_dialog_status_while_the_run_goes(store: Store) -> None:
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(None, None)
    await _first_in_flight(evaluator)
    assert _statuses(runner, run_id) == [("call-024", "evaluating", 0, 8), ("p1-ru-003", "queued", 0, 8)]
    gate.set()
    await _drain(runner)
    assert _statuses(runner, run_id) == [("call-024", "done", 8, 8), ("p1-ru-003", "done", 8, 8)]
    assert {d["error"] for d in runner.progress(run_id)["dialogs"]} == {None}


async def test_dialog_status_carries_the_error_and_missing_answers(store: Store) -> None:
    runner = Runner(store, FakeEvaluator(fail_on={"p1-ru-003"}, skip={"04"}), parallel=1)
    run_id = runner.start(None, None)
    await _drain(runner)
    call, chat = runner.progress(run_id)["dialogs"]
    assert (call["status"], call["done"], call["total"], call["error"]) == (
        "done", 7, 8, "нет ответа модели, ждёт оценки: 04",
    )  # fmt: skip
    assert (chat["status"], chat["done"], chat["error"]) == ("error", 0, "timeout")


async def test_cancelled_run_marks_dialogs_that_never_started(store: Store) -> None:
    gate = asyncio.Event()
    evaluator = FakeEvaluator(gate=gate)
    runner = Runner(store, evaluator, parallel=1)
    run_id = runner.start(None, None)
    await _first_in_flight(evaluator)
    runner.cancel(run_id)
    gate.set()
    await _drain(runner)
    assert [d["status"] for d in runner.progress(run_id)["dialogs"]] == ["done", "cancelled"]


async def test_forced_run_lists_a_dialog_a_human_holds_entirely_as_skipped(store: Store) -> None:
    _answer_all(store)
    _appeal(store, "p1-ru-003", "04", "pending")
    runner = Runner(store, FakeEvaluator(), parallel=1)
    run_id = runner.start(None, ["04"], force=True)
    await _drain(runner)
    dialogs = runner.progress(run_id)["dialogs"]
    assert [(d["id"], d["status"], d["skipped"]) for d in dialogs] == [
        ("call-024", "done", 0), ("p1-ru-003", "skipped", 1),
    ]  # fmt: skip


async def test_forced_run_of_many_dialogs_without_a_list_needs_confirmation(store: Store) -> None:
    store.add_dialogs([d for d in DIALOGS.values() if d.id not in ("call-024", "p1-ru-003")], {})
    runner = Runner(store, FakeEvaluator(), parallel=1)
    with pytest.raises(Invalid, match="^Подтвердите перезапуск 10 диалогов$"):
        runner.start(None, ["01"], force=True)
    assert store.list_runs() == []
    listed = runner.start(list(DIALOGS), ["01"], force=True)  # an explicit list is the confirmation
    await _drain(runner)
    confirmed = runner.start(None, ["01"], force=True, confirm=True)
    await _drain(runner)
    assert [store.get_run(i).total for i in (listed, confirmed)] == [10, 10]  # type: ignore[union-attr]


# --- перепроверка другой моделью: теневые ответы, принятие ---


async def test_compare_run_keeps_new_answers_in_the_shadow(store: Store) -> None:
    _answer_all(store)
    _appeal(store, "call-024", "04", "pending")
    runner = Runner(store, FakeEvaluator(), parallel=1)
    other = FakeEvaluator(res={})  # "yes" / max step / no flags everywhere

    run_id = runner.start(
        ["call-024"], None, apply="compare", override={"llm_provider": "ds"}, evaluator=other, model="ds-pro"
    )
    await _drain(runner)

    run = store.get_run(run_id)
    assert run is not None
    assert (run.apply, run.override, run.model, run.force, run.skipped) == (
        "compare", {"llm_provider": "ds"}, "ds-pro", True, 1,
    )  # fmt: skip
    assert other.order == ["call-024"] and "04" not in other.seen
    assert {r.a for r in _current(store)["call-024"].values()} == {"na"}  # current answers untouched
    shadow = store.result_rows(run_id=run_id)
    assert len(shadow) == 7 and all(r.shadow for r in shadow)


async def test_override_evaluator_serves_one_run_only(store: Store) -> None:
    usual, other = FakeEvaluator(), FakeEvaluator()
    runner = Runner(store, usual, parallel=1)
    runner.start(["call-024"], None, evaluator=other)
    await _drain(runner)
    runner.start(["p1-ru-003"], None)
    await _drain(runner)
    assert (other.order, usual.order) == (["call-024"], ["p1-ru-003"])


async def test_override_alone_is_a_forced_re_check(store: Store) -> None:
    _answer_all(store)
    runner = Runner(store, FakeEvaluator(), parallel=1)
    run_id = runner.start(["call-024"], ["01"], override={"evaluator": "jev"}, evaluator=FakeEvaluator())
    await _drain(runner)
    run = store.get_run(run_id)
    assert run is not None and (run.force, run.total, run.apply) == (True, 1, "replace")


async def test_finished_run_calls_alert_hook_and_survives_its_failure(store: Store) -> None:
    calls: list[int] = []

    async def hook() -> None:
        calls.append(1)
        raise RuntimeError("alerts down")

    plan = plan_run(store, CHECKLIST, None, None)
    run_id = store.add_run(sum(len(cs) for _, cs in plan), 100.0)
    await Runner(store, FakeEvaluator(), parallel=1, on_finish=hook).execute(run_id, CHECKLIST, plan)

    run = store.get_run(run_id)
    assert calls == [1] and run is not None and run.status == "done"
