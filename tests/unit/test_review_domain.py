from types import SimpleNamespace
from typing import Any

import pytest

from cqa.domain.review import allowed_answers


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
