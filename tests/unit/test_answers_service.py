"""Ручной ответ специалиста КК: новый результат пары, итог считает его, модель его не перезаписывает."""

from datetime import datetime

import pytest

from cqa.adapters.store import Store
from cqa.domain.review import ASTANA, fingerprint
from cqa.services.answers import MANUAL, set_answer
from cqa.services.appeals import file_appeal
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.runs import plan_run
from fakes import prototype_checklist, prototype_dialogs

CHECKLIST = prototype_checklist()
FPS = {c.id: fingerprint(CHECKLIST, c, "chat") for c in CHECKLIST.criteria}  # p1-ru-003 — чат
BOOL = next(c for c in CHECKLIST.criteria if c.type == "bool" and not c.na)
SCALE = next(c for c in CHECKLIST.criteria if c.type == "scale")
FLAG = next(c for c in CHECKLIST.criteria if c.type == "flag")
DIALOGS = {d.id: d for d in prototype_dialogs()}


def _current(store: Store, dlg: str, cid: str):  # noqa: ANN202
    return store.current_results(FPS).get(dlg, {}).get(cid)


def test_manual_answer_scores_a_pending_criterion(store: Store) -> None:
    set_answer(store, dlg="p1-ru-003", cid=BOOL.id, a="no", reason="Не поздоровался", by="Специалист КК")
    result = _current(store, "p1-ru-003", BOOL.id)
    assert (result.a, result.why, result.model) == ("no", "Не поздоровался", MANUAL)


def test_manual_answer_replaces_the_model_answer_and_keeps_history(store: Store) -> None:
    store.add_result("p1-ru-003", BOOL.id, 3, FPS[BOOL.id], DIALOGS["p1-ru-003"].res[BOOL.id])
    set_answer(store, dlg="p1-ru-003", cid=BOOL.id, a="no", reason="", by="Специалист КК")
    result = _current(store, "p1-ru-003", BOOL.id)
    assert (result.a, result.model, result.why) == ("no", MANUAL, "Оценено вручную: Специалист КК")


def test_model_run_skips_a_manually_answered_criterion(store: Store) -> None:
    set_answer(store, dlg="p1-ru-003", cid=SCALE.id, a=max(SCALE.steps or [0]), reason="", by="Специалист КК")
    plan = plan_run(store, CHECKLIST, ["p1-ru-003"], None)
    assert SCALE.id not in [c.id for c in plan[0][1]]


def test_flag_answer_needs_every_question_as_a_boolean(store: Store) -> None:
    keys = [q.k for q in FLAG.questions or []]
    set_answer(store, dlg="p1-ru-003", cid=FLAG.id, a={k: k == keys[0] for k in keys}, reason="", by="КК")
    assert _current(store, "p1-ru-003", FLAG.id).a == {k: k == keys[0] for k in keys}
    with pytest.raises(Invalid, match=FLAG.id):
        set_answer(store, dlg="p1-ru-003", cid=FLAG.id, a={keys[0]: True}, reason="", by="КК")


@pytest.mark.parametrize("bad", ["maybe", 7, True, {"x": True}])
def test_answer_outside_the_allowed_values_is_invalid(store: Store, bad: object) -> None:
    with pytest.raises(Invalid, match=BOOL.id):
        set_answer(store, dlg="p1-ru-003", cid=BOOL.id, a=bad, reason="", by="КК")  # type: ignore[arg-type]
    assert _current(store, "p1-ru-003", BOOL.id) is None


def test_unknown_dialog_or_criterion_is_not_found(store: Store) -> None:
    with pytest.raises(NotFound):
        set_answer(store, dlg="nope", cid=BOOL.id, a="yes", reason="", by="КК")
    with pytest.raises(NotFound):
        set_answer(store, dlg="p1-ru-003", cid="nope", a="yes", reason="", by="КК")


def test_blank_author_is_invalid(store: Store) -> None:
    with pytest.raises(Invalid, match="Укажите"):
        set_answer(store, dlg="p1-ru-003", cid=BOOL.id, a="yes", reason="", by=" ")


def test_pending_appeal_blocks_a_manual_answer(store: Store) -> None:
    store.add_result("p1-ru-003", BOOL.id, 3, FPS[BOOL.id], DIALOGS["p1-ru-003"].res[BOOL.id])
    current = _current(store, "p1-ru-003", BOOL.id).a
    file_appeal(
        store, dlg="p1-ru-003", cid=BOOL.id, ask="no" if current == "yes" else "yes", ev=[],
        comment="Оператор не согласен с оценкой", by="Оператор", now=datetime(2026, 11, 7, tzinfo=ASTANA),
    )  # fmt: skip
    with pytest.raises(Conflict, match="апелляция"):
        set_answer(store, dlg="p1-ru-003", cid=BOOL.id, a="no", reason="", by="КК")
