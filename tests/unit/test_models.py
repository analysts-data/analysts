from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from cqa.domain.models import Appeal, Checklist, Criterion, CriterionResult, Dialog, JevQuestion

# JSON examples from design/contract.md, placeholders replaced by concrete values of the same shape
CHECKLIST = {
    "version": 3,
    "rules": "Общие правила чек-листа: N/A только где разрешён, за время ответа не штрафуем.",
    "sections": [
        "Начало и понимание запроса",
        "Безопасность и решение",
        "Ведение и завершение диалога",
        "Грубые нарушения",
    ],
    "criteria": [
        {
            "id": "01",
            "sec": 0,
            "name": "Установление контакта",
            "type": "bool",
            "w": 10,
            "na": False,
            "text": "Да — оператор поздоровался на языке клиента и представился в первом ответе.",
            "channel": "all",
        },
        {
            "id": "04",
            "sec": 1,
            "name": "Корректная и полная консультация",
            "type": "scale",
            "w": 20,
            "na": True,
            "naCond": "Чат закончился до того, как клиент сформулировал запрос.",
            "signal": "resolution",
            "steps": [20, 15, 10, 5, 0],
            "stepText": {"20": "Всё закрыто.", "15": "Почти.", "10": "Часть.", "5": "Мало.", "0": "Нет."},
            "text": "Оцените ответ или следующий шаг по шкале.",
            "channel": "all",
        },
        {
            "id": "08",
            "sec": 3,
            "name": "Грубые ошибки",
            "type": "flag",
            "w": 0,
            "signal": "risk",
            "questions": [{"k": "insult", "label": "Оскорбление клиента", "text": "Было ли оскорбление?"}],
            "text": "Каждый вид нарушения — отдельный вопрос к модели.",
            "channel": "all",
        },
    ],
}

CRITERION_RESULT = {
    "a": 15,
    "alt": 10,
    "ev": [9, 10],
    "seg": "реплики 30–32",
    "why": "Обоснование по-русски.",
    "quote": "дословный фрагмент на языке диалога",
    "tag": "Не назван срок ответа",
    "better": "Как сказать лучше.",
    "evFail": False,
    "model": "qwen3-6",
    "calls": 1,
    "cost": 0.0012,
    "ms": 2100,
}

DIALOG = {
    "id": "p4-ru-002",
    "title": "Звонок p4-ru-002",
    "ch": "call",
    "lang": "RU",
    "dur": 620.4,
    "at": "07.11 13:49",
    "lines": [
        {
            "n": 1,
            "t": 12.3,
            "ts": "2026-11-07T13:49:43.1234567+05:00",
            "who": "client",
            "text": "Алло.",
            "s": 9.1,
            "seg": "conv",
        },
        {
            "fold": True,
            "from": 19,
            "to": 57,
            "t0": 120.0,
            "t1": 545.0,
            "label": "Удержание и разговор с коллегой",
        },
    ],
    "res": {"04": CRITERION_RESULT},
    "reviewed": False,
    "cost": {"calls": 10, "verifier_calls": 1, "usd": 0.0121, "ms": 41000},
}

APPEAL = {
    "id": "a1",
    "kind": "appeal",
    "dlg": "call-024",
    "cid": "04",
    "from": 15,
    "ask": 20,
    "to": None,
    "ev": [30],
    "by": "Оператор",
    "at": "07.11 15:10",
    "status": "pending",
    "comment": "Комментарий заявителя",
    "reviewer": None,
    "reason": None,
    "decidedAt": None,
}


@pytest.mark.parametrize(
    ("model", "example"),
    [(Checklist, CHECKLIST), (CriterionResult, CRITERION_RESULT), (Dialog, DIALOG), (Appeal, APPEAL)],
)
def test_contract_example_round_trips_without_loss(model: type[BaseModel], example: dict[str, Any]) -> None:
    assert model.model_validate(example).model_dump(mode="json", exclude_unset=True) == example


def test_unknown_criterion_type_is_rejected_naming_the_field() -> None:
    with pytest.raises(ValidationError) as err:
        Criterion.model_validate({**CHECKLIST["criteria"][0], "type": "stars"})
    assert err.value.errors()[0]["loc"] == ("type",)


def test_scale_answer_outside_steps_is_rejected() -> None:
    scale = Criterion.model_validate(CHECKLIST["criteria"][1])
    assert scale.accepts(15) and scale.accepts("na")
    assert not scale.accepts(12)
    assert not scale.accepts("yes")


@pytest.mark.parametrize(
    ("kind", "criteria", "expected"),
    [
        ("noul", {"true": "Сделал", "false": "Не сделал"}, {"yes": "Сделал", "no": "Не сделал"}),
        (
            "choice",
            {"yes": "Да", "no": "Нет", "not_applicable": "Нет"},
            {"yes": "Да", "no": "Нет", "na": "Нет"},
        ),
        ("choice", {"yes": "Да", "no": "Нет", "na": "Нет"}, {"yes": "Да", "no": "Нет", "na": "Нет"}),
    ],
)
def test_jev_descriptions_map_source_keys_to_answer_keys(
    kind: Any, criteria: dict[str, str], expected: dict[str, str]
) -> None:
    jev = JevQuestion(type=kind, instructions="Текст", criteria=criteria)
    criterion = Criterion.model_validate({**CHECKLIST["criteria"][0], "jev": jev.model_dump()})
    assert criterion.jev_descriptions() == expected
    assert criterion.jev is not None and criterion.jev.criteria == criteria


def test_criterion_without_jev_has_no_descriptions() -> None:
    assert Criterion.model_validate(CHECKLIST["criteria"][0]).jev_descriptions() == {}
