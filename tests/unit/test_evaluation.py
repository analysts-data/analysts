import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from cqa.domain.models import Checklist, Criterion, Dialog
from cqa.domain.prompt import Message
from cqa.services.evaluation import LlmEvaluator, Reply, Verdict

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CHECKLIST = Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text(encoding="utf-8"))
CRITERIA = {c.id: c for c in CHECKLIST.criteria}
DIALOGS = {
    d["id"]: Dialog.model_validate(d)
    for d in json.loads((FIXTURES / "dialogs_prototype.json").read_text(encoding="utf-8"))
}
CHAT = DIALOGS["p1-ru-022"]
CALL = DIALOGS["call-024"]
FLAG = CRITERIA["08"]
PAID_LABEL = next(q.label for q in FLAG.questions or [] if q.k == "paid")


def topic(messages: list[Message]) -> str:
    """Id критерия или `08:<k>` подвопроса, о котором спрашивает первое сообщение user."""
    user = messages[1]["content"]
    for c in CHECKLIST.criteria:
        for q in c.questions or []:
            if f"Нарушение для проверки:\n{q.text or q.label}\n" in user:
                return f"{c.id}:{q.k}"
        if c.type != "flag" and f"Критерий:\n{c.text}\n" in user:
            return c.id
    raise AssertionError("неизвестный вопрос")


def default(key: str) -> dict[str, Any]:
    if ":" in key:
        return {"reason_ru": "Нарушения нет", "violation_found": False}
    c = CRITERIA[key]
    return {"reason_ru": "Выполнено", "answer": max(c.steps) if c.steps else "yes"}


class FakeModel:
    """Ответы по ключу вопроса по очереди; без очереди — верный ответ «да» или максимум шкалы."""

    def __init__(self, replies: dict[str, list[Any]] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> Reply:
        self.calls.append(messages)
        key = topic(messages)
        queue = self.replies.get(key)
        reply = queue.pop(0) if queue else default(key)
        if isinstance(reply, Exception):
            raise reply
        return Reply(
            text=reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False), cost=0.01, ms=100
        )

    def keys(self) -> list[str]:
        return [topic(m) for m in self.calls]


class FakeVerifier:
    def __init__(self) -> None:
        self.criteria: list[list[str]] = []

    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict:
        self.criteria.append([c.id for c in criteria])
        return Verdict(answers={}, cost=0.0002)


def evaluator(model: FakeModel, verifier: FakeVerifier | None = None) -> LlmEvaluator:
    return LlmEvaluator(
        model,
        model_name="qwen3-6",
        reasoning="on",
        anonymize=False,
        verifier=verifier,
        sends_real_data=False,
        allow_real_data=False,
    )


async def test_chat_makes_one_call_per_criterion_and_flag_question() -> None:
    model = FakeModel()
    out = await evaluator(model).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)
    assert len(model.calls) == 10
    assert [e.cid for e in out.results] == [c.id for c in CHECKLIST.criteria]
    assert (out.verifier_calls, out.verifier_usd) == (0, 0.0)
    first = out.results[0].result
    assert (first.a, first.model, first.calls, first.cost, first.ms, first.evFail) == (
        "yes",
        "qwen3-6",
        1,
        0.01,
        100,
        False,
    )
    flag = out.results[-1].result
    assert flag.a == {"insult": False, "paid": False, "leak": False}
    assert (flag.calls, flag.cost, flag.ms) == (3, pytest.approx(0.03), 300)


async def test_results_follow_order_of_criteria_argument() -> None:
    criteria = [CRITERIA["06"], CRITERIA["01"], CRITERIA["04"]]
    out = await evaluator(FakeModel()).evaluate(CHAT, CHECKLIST, criteria)
    assert [e.cid for e in out.results] == ["06", "01", "04"]
    assert [e.result.a for e in out.results] == [10, "yes", 20]


async def test_flag_is_found_when_one_question_finds_a_violation() -> None:
    paid = {
        "reason_ru": "Предложил",
        "turn_ids": [6],
        "quote": "Готовые портфели есть в приложении",
        "violation_found": True,
    }
    model = FakeModel({"08:paid": [paid]})
    out = await evaluator(model).evaluate(CHAT, CHECKLIST, [FLAG])
    [flag] = out.results
    assert flag.result.a == {"insult": False, "paid": True, "leak": False}
    assert (flag.result.ev, flag.result.tag, flag.result.evFail) == ([6], PAID_LABEL, False)


async def test_same_evaluation_twice_sends_two_requests_and_keeps_no_cache_key() -> None:
    model = FakeModel()
    ev = evaluator(model)
    first = await ev.evaluate(CHAT, CHECKLIST, [CRITERIA["01"]])
    second = await ev.evaluate(CHAT, CHECKLIST, [CRITERIA["01"]])
    assert len(model.calls) == 2
    assert first == second
    assert [f.name for f in dataclasses.fields(first.results[0])] == ["cid", "result"]
