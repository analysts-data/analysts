"""Runs: plan of pairs without a current result, ordered workers, cancel and resume, honest progress."""

import json
from pathlib import Path

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Checklist, Dialog
from cqa.domain.review import fingerprint
from cqa.services.runs import eta_seconds, plan_run

FIXTURES = Path(__file__).parents[1] / "fixtures"
CHECKLIST = Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text(encoding="utf-8"))
DIALOGS = {
    d["id"]: Dialog.model_validate(d)
    for d in json.loads((FIXTURES / "dialogs_prototype.json").read_text(encoding="utf-8"))
}


@pytest.fixture
def store() -> Store:
    store = Store(connect(":memory:"))
    store.add_checklist(CHECKLIST, "начальная версия")
    store.add_dialogs([DIALOGS["call-024"], DIALOGS["p1-ru-003"]], {})
    return store


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
        store.add_result("call-024", c.id, 3, fingerprint(CHECKLIST, c), DIALOGS["call-024"].res[c.id])
    assert _ids(plan_run(store, CHECKLIST, None, None)) == [("p1-ru-003", ALL)]


def test_plan_ignores_results_of_another_meaning(store: Store) -> None:
    store.add_result("call-024", "04", 3, "0000000000000000", DIALOGS["call-024"].res["04"])
    assert _ids(plan_run(store, CHECKLIST, ["call-024"], ["04"])) == [("call-024", ["04"])]


def test_plan_limits_criteria_to_the_argument(store: Store) -> None:
    assert _ids(plan_run(store, CHECKLIST, None, ["04"])) == [("call-024", ["04"]), ("p1-ru-003", ["04"])]


def test_plan_follows_the_order_of_the_dialogs_argument(store: Store) -> None:
    plan = plan_run(store, CHECKLIST, ["p1-ru-003", "call-024"], None)
    assert [d.id for d, _ in plan] == ["p1-ru-003", "call-024"]


def test_plan_does_not_repeat_a_dialog_listed_twice(store: Store) -> None:
    assert [d.id for d, _ in plan_run(store, CHECKLIST, ["call-024", "call-024"], None)] == ["call-024"]


def test_plan_does_not_check_unknown_ids(store: Store) -> None:
    assert _ids(plan_run(store, CHECKLIST, ["nope", "call-024"], ["99", "04"])) == [("call-024", ["04"])]
