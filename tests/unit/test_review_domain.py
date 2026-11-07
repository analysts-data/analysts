from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from cqa.domain.review import allowed_answers, effective_answer, needs_review, stamp


# TODO: заменить на Criterion.model_validate, когда models.py появится в main
def crit(**kw: Any) -> Any:
    base: dict[str, Any] = {"id": "04", "sec": 0, "name": "Критерий", "type": "bool", "w": 10, "na": False}
    return SimpleNamespace(**{"steps": None, **base, **kw})


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


# TODO: заменить на CriterionResult и Appeal, когда models.py появится в main
def result(**kw: Any) -> Any:
    return SimpleNamespace(**{"a": 5, "alt": None, "evFail": None, **kw})


def decision(kind: str, status: str, to: Any) -> Any:
    return SimpleNamespace(kind=kind, status=status, to=to)


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
