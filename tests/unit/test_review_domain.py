import copy
from datetime import UTC, datetime
from typing import Any

import pytest

from cqa.domain.models import Appeal, Checklist, Criterion, CriterionResult
from cqa.domain.review import (
    allowed_answers,
    diff_checklists,
    effective_answer,
    fingerprint,
    needs_review,
    stamp,
    version_note,
)

CL: dict[str, Any] = {
    "version": 3,
    "rules": "Общие правила",
    "sections": ["Начало", "Завершение"],
    "criteria": [
        {"id": "04", "sec": 0, "name": "Консультация", "type": "scale", "w": 20, "na": True,
         "naCond": "Запроса нет", "signal": "resolution", "steps": [20, 15, 10, 5, 0],
         "stepText": {"20": "a", "15": "b", "10": "c", "5": "d", "0": "e"},
         "text": "Оцените ответ", "channel": "all"},
        {"id": "06", "sec": 1, "name": "Шестой", "type": "bool", "w": 15, "na": False,
         "text": "Да — сделал", "channel": "all"},
        {"id": "07", "sec": 1, "name": "Седьмой", "type": "bool", "w": 5, "na": False,
         "text": "Да — попрощался", "channel": "all"},
        {"id": "08", "sec": 1, "name": "Грубые", "type": "flag", "w": 0, "signal": "risk",
         "questions": [{"k": "insult", "label": "Оскорбление", "text": "Было?"}],
         "text": "Нарушения", "channel": "all"},
    ],
}  # fmt: skip


def draft(
    edits: dict[str, dict[str, Any]] | None = None,
    remove: tuple[str, ...] = (),
    add: tuple[dict[str, Any], ...] = (),
    **top: Any,
) -> Checklist:
    """Черновик из CL: правки полей критериев по id, удаление, добавление и правки полей чек-листа."""
    data = {**copy.deepcopy(CL), **top}
    kept = [{**c, **(edits or {}).get(c["id"], {})} for c in data["criteria"] if c["id"] not in remove]
    data["criteria"] = kept + list(add)
    return Checklist.model_validate(data)


def edit(cid: str, **upd: Any) -> Checklist:
    return draft({cid: upd})


def by_id(cl: Checklist, cid: str) -> Criterion:
    return next(c for c in cl.criteria if c.id == cid)


def fp(cl: Checklist, cid: str, ch: str = "chat") -> str:
    return fingerprint(cl, by_id(cl, cid), ch)


def crit(**kw: Any) -> Criterion:
    base = {"id": "04", "sec": 0, "name": "Критерий", "type": "bool", "w": 10, "text": "Текст"}
    return Criterion.model_validate({**base, **kw})


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"type": "bool", "na": False}, ["yes", "no"]),
        ({"type": "bool", "na": True}, ["yes", "no", "na"]),
        ({"type": "scale", "na": True, "steps": [20, 15, 10, 5, 0]}, [20, 15, 10, 5, 0, "na"]),
        ({"type": "flag", "w": 0}, []),
    ],
)
def test_allowed_answers_follow_criterion_type_and_na(kw: dict[str, Any], expected: list[Any]) -> None:
    assert allowed_answers(crit(**kw)) == expected


@pytest.mark.parametrize(("field", "value"), [("name", "Другое"), ("w", 5), ("sec", 1), ("signal", "risk")])
def test_fingerprint_ignores_light_fields(field: str, value: Any) -> None:
    assert fp(edit("04", **{field: value}), "04") == fp(draft(), "04")


@pytest.mark.parametrize(
    ("cid", "field", "value"),
    [
        ("04", "text", "Новый текст"),
        ("04", "type", "bool"),
        ("04", "steps", [20, 10, 0]),
        ("04", "stepText", {"20": "x", "15": "b", "10": "c", "5": "d", "0": "e"}),
        ("04", "na", False),
        ("04", "naCond", "Другое условие"),
        ("08", "questions", [{"k": "threat", "label": "Угроза", "text": "Было?"}]),
        ("04", "channel", "chat"),
        (
            "06",
            "jev",
            {"type": "noul", "instructions": "Да — сделал", "criteria": {"true": "a", "false": "b"}},
        ),
    ],
)
def test_fingerprint_changes_with_meaning(cid: str, field: str, value: Any) -> None:
    assert fp(edit(cid, **{field: value}), cid) != fp(draft(), cid)


def test_fingerprint_changes_with_rules() -> None:
    assert fp(draft(rules="Другие правила"), "06") != fp(draft(), "06")


def test_call_addendum_changes_only_the_call_fingerprint() -> None:
    with_call = edit("04", call="Уточнение для звонка")
    assert fp(with_call, "04", "chat") == fp(draft(), "04", "chat")
    assert fp(with_call, "04", "call") != fp(draft(), "04", "call")


def test_without_addendum_call_and_chat_fingerprints_match() -> None:
    assert fp(draft(), "04", "call") == fp(draft(), "04", "chat")


def test_call_addendum_change_is_pending() -> None:
    assert diff_checklists(draft(), edit("04", call="Уточнение для звонка")).pending == ["04"]


def test_fingerprint_without_jev_matches_the_snapshot_before_jev() -> None:
    # отпечатки до поля jev: при jev = null кэш ответов не сбрасывается
    before = {
        "04": "0b5182d318764895",
        "06": "34aaebdb6fe05be1",
        "07": "623b5651bca74be8",
        "08": "0f3c2a9dc7c3aa5d",
    }
    for ch in ("chat", "call"):
        assert {c.id: fingerprint(draft(), c, ch) for c in draft().criteria} == before


def test_fingerprint_has_16_chars() -> None:
    assert len(fp(draft(), "04")) == 16


NEW_09 = {"id": "09", "sec": 1, "name": "Новый", "type": "bool", "w": 5, "text": "Да — новое"}


def test_weight_only_change_is_light() -> None:
    d = diff_checklists(draft(), draft({"06": {"w": 10}}))
    assert (d.pending, d.light, d.removed, d.rules, d.changed) == ([], ["06"], [], False, True)
    assert version_note(d) == "веса или названия 06"


def test_meaning_weight_and_removal_build_note_in_order() -> None:
    d = diff_checklists(draft(), draft({"04": {"text": "Новый текст"}, "06": {"w": 10}}, remove=("07",)))
    assert (d.pending, d.light, d.removed) == (["04"], ["06"], ["07"])
    assert version_note(d) == "изменены 04; веса или названия 06; удалены 07"


def test_new_criterion_is_pending() -> None:
    d = diff_checklists(draft(), draft(add=(NEW_09,)))
    assert d.pending == ["09"]
    assert version_note(d) == "изменены 09"


def test_rules_change_makes_every_criterion_pending() -> None:
    d = diff_checklists(draft(), draft(rules="Другие правила"))
    assert d.rules is True
    assert d.pending == ["04", "06", "07", "08"]
    assert version_note(d) == "изменены общие правила"


def test_section_rename_changes_checklist_without_criteria() -> None:
    d = diff_checklists(draft(), draft(sections=["Начало", "Конец"]))
    assert (d.pending, d.light, d.removed, d.changed) == ([], [], [], True)
    assert version_note(d) == "изменены секции"


def test_version_only_difference_is_no_change() -> None:
    assert diff_checklists(draft(), draft(version=4)).changed is False


def result(**kw: Any) -> CriterionResult:
    return CriterionResult.model_validate({"a": 5, **kw})


def decision(kind: str, status: str, to: Any) -> Appeal:
    return Appeal.model_validate(
        {"id": "a1", "kind": kind, "dlg": "p1-ru-003", "cid": "04", "from": 5, "to": to,
         "by": "Оператор", "at": "07.11 15:10", "status": status, "comment": "Комментарий"}
    )  # fmt: skip


def test_effective_answer_without_decisions_is_model_answer() -> None:
    assert effective_answer(result(a=5), []) == 5


def test_effective_answer_takes_last_decision() -> None:
    decided = [decision("appeal", "changed", 10), decision("appeal", "confirmed", 10)]
    assert effective_answer(result(a=5), decided) == 10


def test_effective_answer_ignores_pending_and_closed_records() -> None:
    records = [decision("appeal", "pending", None), decision("appeal", "closed", None)]
    assert effective_answer(result(a=5), records) == 5


def test_effective_answer_counts_review_records() -> None:
    assert effective_answer(result(a=15), [decision("review", "changed", 10)]) == 10


@pytest.mark.parametrize(
    ("ctype", "kw", "expected"),
    [
        ("scale", {"a": 15, "alt": 10}, True),
        ("scale", {"a": 15, "alt": 15}, False),
        ("bool", {"a": "yes"}, False),
        ("bool", {"a": "yes", "evFail": True}, True),
        ("flag", {"a": {"insult": True}, "alt": {"insult": False}}, False),
    ],
)
def test_needs_review_on_disagreement_or_failed_evidence(
    ctype: str, kw: dict[str, Any], expected: bool
) -> None:
    assert needs_review(crit(type=ctype), result(**kw)) is expected


def test_stamp_uses_astana_time() -> None:
    assert stamp(datetime(2026, 11, 7, 10, 10, tzinfo=UTC)) == "07.11 15:10"
