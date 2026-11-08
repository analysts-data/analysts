"""История оценок пары: новые первыми, текущая строка, прежний смысл; возврат прежней оценки."""

from datetime import datetime

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import ASTANA, fingerprint
from cqa.services.answers import MANUAL, set_answer
from cqa.services.appeals import file_appeal
from cqa.services.errors import Conflict, NotFound
from cqa.services.history import adopt, history, restore
from fakes import prototype_checklist

CHECKLIST = prototype_checklist()
BOOL = next(c for c in CHECKLIST.criteria if c.type == "bool" and not c.na)
OTHER = next(c for c in CHECKLIST.criteria if c.id != BOOL.id)
FP = fingerprint(CHECKLIST, BOOL, "chat")  # p1-ru-003 — чат


def _two_runs(store: Store) -> tuple[int, int]:
    first, second = store.add_run(1, 0.0), store.add_run(1, 1.0)
    store.add_result(
        "p1-ru-003", BOOL.id, 3, FP, CriterionResult(a="no", why="Нет", ev=[2], model="m1"), first
    )
    store.add_result("p1-ru-003", BOOL.id, 3, FP, CriterionResult(a="yes", why="Да", model="m2"), second)
    return first, second


def test_history_lists_every_answer_newest_first_and_marks_the_current_one(store: Store) -> None:
    first, second = _two_runs(store)

    got = history(store, "p1-ru-003")

    assert list(got) == [BOOL.id]
    newest, oldest = got[BOOL.id]
    assert {k: newest[k] for k in ("run_id", "model", "a", "why", "ev", "current", "stale", "version")} == {
        "run_id": second, "model": "m2", "a": "yes", "why": "Да", "ev": [], "current": True, "stale": False,
        "version": 3,
    }  # fmt: skip
    assert (oldest["run_id"], oldest["a"], oldest["ev"], oldest["current"]) == (first, "no", [2], False)
    assert newest["id"] > oldest["id"] and isinstance(newest["created"], str)


def test_answers_of_an_older_meaning_are_stale(store: Store) -> None:
    _two_runs(store)
    criteria = [
        c.model_copy(update={"text": "Новый смысл"}) if c.id == BOOL.id else c for c in CHECKLIST.criteria
    ]
    store.add_checklist(CHECKLIST.model_copy(update={"version": 4, "criteria": criteria}), "смысл изменён")

    rows = history(store, "p1-ru-003")[BOOL.id]

    assert [(r["stale"], r["current"]) for r in rows] == [(True, False), (True, False)]


def test_history_of_an_unknown_dialog_is_not_found(store: Store) -> None:
    with pytest.raises(NotFound, match="nope"):
        history(store, "nope")


def test_restore_appends_a_copy_that_becomes_current(store: Store) -> None:
    first, _ = _two_runs(store)
    old = history(store, "p1-ru-003")[BOOL.id][1]

    result = restore(store, old["id"])

    assert (result.a, result.model) == ("no", "m1")
    assert store.current_results({BOOL.id: FP})["p1-ru-003"][BOOL.id] == result
    rows = history(store, "p1-ru-003")[BOOL.id]
    assert [(r["a"], r["run_id"], r["current"]) for r in rows] == [
        ("no", first, True), ("yes", rows[1]["run_id"], False), ("no", first, False),
    ]  # fmt: skip


def test_restore_is_refused_while_an_appeal_is_pending(store: Store) -> None:
    _two_runs(store)
    old = history(store, "p1-ru-003")[BOOL.id][1]
    file_appeal(
        store, dlg="p1-ru-003", cid=BOOL.id, ask="no", ev=[], comment="Оператор не согласен с оценкой",
        by="Оператор", now=datetime(2026, 11, 7, tzinfo=ASTANA),
    )  # fmt: skip
    with pytest.raises(Conflict, match="апелляц"):
        restore(store, old["id"])
    assert store.current_results({BOOL.id: FP})["p1-ru-003"][BOOL.id].a == "yes"


def test_restore_of_an_answer_to_an_older_meaning_is_refused(store: Store) -> None:
    store.add_result("p1-ru-003", OTHER.id, 3, "0000000000000000", CriterionResult(a="yes"))
    (row,) = history(store, "p1-ru-003")[OTHER.id]
    with pytest.raises(Conflict, match="прежн"):
        restore(store, row["id"])


def test_restore_of_the_current_answer_is_refused(store: Store) -> None:
    _two_runs(store)
    current = history(store, "p1-ru-003")[BOOL.id][0]
    with pytest.raises(Conflict, match="уже текущая"):
        restore(store, current["id"])


def test_restore_of_an_unknown_result_is_not_found(store: Store) -> None:
    with pytest.raises(NotFound, match="999"):
        restore(store, 999)


# --- теневые ответы запуска compare ---


def _compare_run(store: Store) -> int:
    run_id = store.add_run(2, 2.0, apply="compare", override={"llm_provider": "ds"})
    store.add_result(
        "p1-ru-003", BOOL.id, 3, FP, CriterionResult(a="no", model="ds-pro"), run_id, shadow=True
    )
    other_fp = fingerprint(CHECKLIST, OTHER, "chat")
    store.add_result(
        "p1-ru-003", OTHER.id, 3, other_fp, CriterionResult(a="na", model="ds-pro"), run_id, shadow=True
    )
    return run_id


def test_history_shows_shadow_answers_with_the_settings_of_their_run(store: Store) -> None:
    _, second = _two_runs(store)
    run_id = _compare_run(store)

    rows = history(store, "p1-ru-003")[BOOL.id]

    assert [(r["run_id"], r["shadow"], r["current"], r["override"]) for r in rows] == [
        (run_id, True, False, {"llm_provider": "ds"}),
        (second, False, True, None),
        (rows[2]["run_id"], False, False, None),
    ]  # fmt: skip


def test_restore_of_a_shadow_answer_makes_it_current(store: Store) -> None:
    _two_runs(store)
    run_id = _compare_run(store)
    shadow = history(store, "p1-ru-003")[BOOL.id][0]

    assert restore(store, shadow["id"]).a == "no"

    newest = history(store, "p1-ru-003")[BOOL.id][0]
    assert (newest["a"], newest["run_id"], newest["shadow"], newest["current"]) == ("no", run_id, False, True)


def test_adopt_makes_shadow_answers_of_a_run_current_except_held_pairs(store: Store) -> None:
    _two_runs(store)
    run_id = _compare_run(store)
    set_answer(store, dlg="p1-ru-003", cid=OTHER.id, a="yes", reason="", by="Специалист КК")

    assert adopt(store, run_id, None, None) == {"adopted": 1, "skipped": 1}

    current = store.current_results({BOOL.id: FP})["p1-ru-003"][BOOL.id]
    assert (current.a, current.model) == ("no", "ds-pro")
    assert history(store, "p1-ru-003")[OTHER.id][0]["model"] == MANUAL


def test_adopt_can_take_a_part_of_the_run(store: Store) -> None:
    run_id = _compare_run(store)
    assert adopt(store, run_id, ["p1-ru-003"], [OTHER.id]) == {"adopted": 1, "skipped": 0}
    assert BOOL.id not in store.current_results({BOOL.id: FP}).get("p1-ru-003", {})


def test_adopt_of_a_replace_run_or_an_unknown_run_is_refused(store: Store) -> None:
    first, _ = _two_runs(store)
    with pytest.raises(Conflict, match="сразу"):
        adopt(store, first, None, None)
    with pytest.raises(NotFound, match="999"):
        adopt(store, 999, None, None)
