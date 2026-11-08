"""Оценщик и обезличивание: модели видят только метки (задачи 5.6–5.7)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from cqa.domain.models import Checklist, Criterion, Dialog, Line
from cqa.services.evaluation import LlmEvaluator, RealDataBlocked, Reply, Verdict

_PERSONAL = "мой ИИН 900101300123, телефон +7 701 123 45 67"
_LABEL_QUOTE = "ИИН [ДАННЫЕ_ИДЕНТИФИКАЦИИ]"


def _criterion() -> Criterion:
    return Criterion(
        id="01",
        sec=0,
        name="Тестовый критерий",
        type="bool",
        w=10.0,
        na=False,
        text="Оператор поздоровался в первом ответе.",
    )


def _chat(text: str = _PERSONAL) -> Dialog:
    return Dialog(
        id="d-1",
        ch="chat",
        lang="RU",
        at="07.11 13:49",
        lines=[Line(n=1, t="00:01", who="client", text=text)],
    )


def _call() -> Dialog:
    return Dialog(
        id="c-1",
        ch="call",
        lang="RU",
        at="07.11 13:49",
        lines=[Line(n=1, t=12.3, who="client", text="Алло.")],
    )


def _checklist() -> Checklist:
    return Checklist(version=1, rules="Общие правила теста", sections=["Раздел"], criteria=[])


@dataclass
class FakeModel:
    """Подделка ChatModel: отвечает заготовкой и записывает всё увиденное."""

    reply: str
    seen: list[str] = field(default_factory=list)
    calls: int = 0

    async def complete(self, messages: list[dict[str, str]]) -> Reply:
        self.calls += 1
        self.seen.extend(message["content"] for message in messages)
        return Reply(text=self.reply, cost=0.0, ms=1)


@dataclass
class FakeVerifier:
    """Подделка Verifier: записывает текст диалога и критерии."""

    seen_text: str = ""
    seen_criteria: list[Criterion] = field(default_factory=list)
    calls: int = 0

    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict:
        self.calls += 1
        self.seen_text = dialog_text
        self.seen_criteria = list(criteria)
        return Verdict(answers={}, cost=0.0)


def _reply_json(quote: str) -> str:
    return json.dumps(
        {
            "reason_ru": "Проверено",
            "turn_ids": [1],
            "quote": quote,
            "checked_range": None,
            "answer": "yes",
            "tag": "",
            "better": "",
        },
        ensure_ascii=False,
    )


def _evaluator(
    model: FakeModel,
    verifier: FakeVerifier | None = None,
    *,
    anonymize: bool = True,
    sends_real_data: bool = False,
    allow_real_data: bool = False,
) -> LlmEvaluator:
    return LlmEvaluator(
        model,
        model_name="qwen3-6",
        reasoning="on",
        anonymize=anonymize,
        verifier=verifier,
        sends_real_data=sends_real_data,
        allow_real_data=allow_real_data,
    )


async def test_model_and_verifier_see_only_labels_when_anonymize_on() -> None:
    model = FakeModel(_reply_json(_LABEL_QUOTE))
    verifier = FakeVerifier()

    await _evaluator(model, verifier).evaluate(_chat(), _checklist(), [_criterion()])

    seen = "\n".join(model.seen)
    assert "[ДАННЫЕ_ИДЕНТИФИКАЦИИ]" in seen
    assert "[ТЕЛЕФОН]" in seen
    assert "900101300123" not in seen
    assert "701 123 45 67" not in seen
    assert "[ДАННЫЕ_ИДЕНТИФИКАЦИИ]" in verifier.seen_text
    assert "900101300123" not in verifier.seen_text


@pytest.mark.parametrize("anonymize", [True, False])
async def test_operator_field_never_reaches_the_model(anonymize: bool) -> None:
    model, verifier = FakeModel(_reply_json("Привет")), FakeVerifier()
    dialog = _chat("Привет").model_copy(update={"operator": "Сотрудник Тестовый"})

    await _evaluator(model, verifier, anonymize=anonymize).evaluate(dialog, _checklist(), [_criterion()])

    assert model.seen and verifier.seen_text
    assert "Тестовый" not in "\n".join(model.seen) + verifier.seen_text


async def test_quote_with_label_passes_evidence_check() -> None:
    model = FakeModel(_reply_json(_LABEL_QUOTE))

    verdict = await _evaluator(model).evaluate(_chat(), _checklist(), [_criterion()])

    result = verdict.results[0].result
    assert result.evFail is False
    assert result.ev == [1]
    assert model.calls == 1


async def test_anonymize_off_sends_original_text() -> None:
    model = FakeModel(_reply_json("мой ИИН 900101300123"))

    await _evaluator(model, anonymize=False).evaluate(_chat(), _checklist(), [_criterion()])

    seen = "\n".join(model.seen)
    assert "900101300123" in seen
    assert "701 123 45 67" in seen


async def test_real_call_is_blocked_in_live_mode_before_any_request() -> None:
    model = FakeModel(_reply_json("не важно"))
    verifier = FakeVerifier()

    evaluator = _evaluator(model, verifier, sends_real_data=True, allow_real_data=False)
    with pytest.raises(RealDataBlocked):
        await evaluator.evaluate(_call(), _checklist(), [_criterion()])

    assert model.calls == 0
    assert verifier.calls == 0


async def test_chat_proceeds_in_live_mode_without_permission() -> None:
    model = FakeModel(_reply_json(_LABEL_QUOTE))

    await _evaluator(model, sends_real_data=True, allow_real_data=False).evaluate(
        _chat(), _checklist(), [_criterion()]
    )

    assert model.calls == 1


async def test_call_proceeds_in_replay_mode() -> None:
    model = FakeModel(_reply_json("Алло."))

    await _evaluator(model, sends_real_data=False, allow_real_data=False).evaluate(
        _call(), _checklist(), [_criterion()]
    )

    assert model.calls == 1
