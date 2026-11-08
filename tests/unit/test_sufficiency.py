"""Достаточность данных диалога (docs/insufficient-data.md): ключевые правила на синтетических диалогах."""

import pytest

from cqa.domain.models import CriterionResult, Dialog, Sufficiency
from cqa.domain.sufficiency import UNSUPPORTED, assess, mark_unsupported

FULL = [
    ("operator", "Здравствуйте, меня зовут Анна. Чем помочь?"),
    ("client", "Не приходит код подтверждения"),
    ("operator", "Проверьте номер в профиле, код придёт в течение минуты"),
    ("client", "Пришёл, спасибо"),
    ("operator", "Рада помочь, хорошего дня"),
]


def dialog(lines: list[tuple[str, str]], *, lang: str = "RU") -> Dialog:
    return Dialog.model_validate(
        {
            "id": "syn-1",
            "ch": "chat",
            "lang": lang,
            "at": "08.11 09:00",
            "lines": [
                {"n": i, "t": f"00:{i:02d}", "who": w, "text": t, "seg": "conv"}
                for i, (w, t) in enumerate(lines, 1)
            ],
        }
    )


def test_complete_dialog_has_enough_data_by_default() -> None:
    assert assess(dialog(FULL), has_audio=True, outcomes={}) == Sufficiency(status="ok")


@pytest.mark.parametrize(
    ("lines", "rule", "basis"),
    [
        ([("bot", "Чем помочь?"), ("system", "Клиент покинул чат")], "bot_only",
         "реплик клиента и оператора нет, реплик бота и системы — 2"),
        ([("bot", "Чем помочь?"), ("client", "Где перевод?"), ("client", "Алло?")], "no_operator",
         "реплик клиента — 2, реплик оператора нет"),
    ],
)  # fmt: skip
def test_nothing_to_assess_blocks_the_dialog(lines: list[tuple[str, str]], rule: str, basis: str) -> None:
    s = assess(dialog(lines), has_audio=True, outcomes={})
    assert s.status == "block"
    assert [(r.id, r.basis, r.outcome) for r in s.reasons] == [(rule, basis, "block")]


def test_short_dialog_is_flagged_and_outcome_is_configurable() -> None:
    d = dialog(FULL[:2])  # оператор и клиент: последняя реплика клиента, завершения нет
    s = assess(d, has_audio=True, outcomes={})
    assert (s.status, [r.id for r in s.reasons]) == ("flag", ["too_short", "truncated"])
    assert assess(d, has_audio=True, outcomes={"too_short": "block"}).status == "block"


FLAGGED = Sufficiency.model_validate(
    {"status": "flag", "reasons": [{"id": "too_short", "text": "t", "basis": "b", "outcome": "flag"}]}
)


@pytest.mark.parametrize(
    ("result", "marked"),
    [
        (CriterionResult(a="yes"), True),
        (CriterionResult(a="no", ev=[2]), False),
        (CriterionResult(a="no", seg="реплики 3–4"), False),
        (CriterionResult(a="na"), False),
        (CriterionResult(a={"insult": False}), False),
        (CriterionResult(a="yes", model="вручную"), False),
    ],
)
def test_answer_without_basis_on_flagged_dialog_needs_review(result: CriterionResult, marked: bool) -> None:
    out = mark_unsupported({"01": result}, FLAGGED)["01"]
    assert out.a == result.a  # ответ не меняется никогда
    assert out.reviewWhy == (UNSUPPORTED if marked else None)
    assert mark_unsupported({"01": result}, Sufficiency(status="ok"))["01"].reviewWhy is None
