import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from cqa.adapters.llm import ModelUnavailable
from cqa.domain.models import Checklist, Criterion, Dialog
from cqa.domain.prompt import SYSTEM_PROMPT, Message, render_dialog, sound_block
from cqa.services.errors import NotFound, Upstream
from cqa.services.evaluation import JevEvaluator, LlmEvaluator, RealDataBlocked, Reply, Verdict

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


BAD_QUOTE = {"reason_ru": "Поздоровался", "turn_ids": [4], "quote": "Добрый вечер", "answer": "yes"}
GOOD_QUOTE = {
    "reason_ru": "Поздоровался",
    "turn_ids": [4],
    "quote": "Здравствуйте! Меня зовут",
    "answer": "yes",
}


async def test_retry_sends_previous_answer_with_errors_and_accepts_fixed_answer() -> None:
    model = FakeModel({"01": [BAD_QUOTE, GOOD_QUOTE]})
    [ev] = (await evaluator(model).evaluate(CHAT, CHECKLIST, [CRITERIA["01"]])).results
    assert (ev.result.calls, ev.result.evFail, ev.result.ev, ev.result.cost) == (2, False, [4], 0.02)
    first, second = model.calls
    assert second[:2] == first
    assert second[2] == {"role": "assistant", "content": json.dumps(BAD_QUOTE, ensure_ascii=False)}
    assert second[3]["role"] == "user"
    assert second[3]["content"].startswith("Ответ не прошёл проверку: ")
    assert "цитата" in second[3]["content"]
    assert second[3]["content"].endswith("Исправь и верни один объект JSON целиком.")


async def test_two_failed_checks_keep_allowed_answer_marked_for_review() -> None:
    model = FakeModel({"01": [BAD_QUOTE, BAD_QUOTE]})
    [ev] = (await evaluator(model).evaluate(CHAT, CHECKLIST, [CRITERIA["01"]])).results
    assert (ev.result.a, ev.result.evFail, ev.result.ev, ev.result.quote, ev.result.calls) == (
        "yes",
        True,
        [],
        None,
        2,
    )


async def test_criterion_without_json_twice_is_left_pending() -> None:
    model = FakeModel({"05": ["Оператор вежлив, ответ — да", "Да"]})
    out = await evaluator(model).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)
    assert [e.cid for e in out.results] == ["01", "02", "03", "04", "06", "07", "08"]
    assert model.keys().count("05") == 2


async def test_flag_question_with_unproven_violation_keeps_it_and_marks_flag() -> None:
    unproven = {"reason_ru": "Предложил", "violation_found": True}
    model = FakeModel({"08:paid": [unproven, unproven]})
    [flag] = (await evaluator(model).evaluate(CHAT, CHECKLIST, [FLAG])).results
    assert flag.result.a == {"insult": False, "paid": True, "leak": False}
    assert (flag.result.ev, flag.result.evFail, flag.result.calls) == ([], True, 4)


async def test_criterion_for_other_channel_is_na_without_model_or_verifier() -> None:
    chat_only = CRITERIA["05"].model_copy(update={"channel": "chat", "na": True})
    criteria = [CRITERIA["01"], chat_only, CRITERIA["07"]]
    model, verifier = FakeModel(), FakeVerifier()
    out = await evaluator(model, verifier).evaluate(CALL, CHECKLIST, criteria)
    assert [e.cid for e in out.results] == ["01", "05", "07"]
    res = out.results[1].result
    assert res.model_dump(exclude_unset=True) == {
        "a": "na",
        "why": "Критерий для другого канала",
        "model": "qwen3-6",
        "calls": 0,
        "cost": 0.0,
        "ms": 0,
    }
    assert model.keys() == ["01", "07"]
    assert verifier.criteria == [["01", "07"]]
    assert (out.verifier_calls, out.verifier_usd) == (1, 0.0002)


async def test_criterion_for_same_channel_is_asked() -> None:
    call_only = CRITERIA["05"].model_copy(update={"channel": "call", "na": True})
    model = FakeModel()
    [ev] = (await evaluator(model).evaluate(CALL, CHECKLIST, [call_only])).results
    assert (ev.result.a, ev.result.calls, model.keys()) == ("yes", 1, ["05"])


async def test_call_addendum_reaches_the_model_only_on_calls() -> None:
    with_call = CRITERIA["01"].model_copy(update={"call": "Уточнение для звонка."})
    model = FakeModel()
    await evaluator(model).evaluate(CHAT, CHECKLIST, [with_call])
    await evaluator(model).evaluate(CALL, CHECKLIST, [with_call])
    assert ["Уточнение для звонка." in m[1]["content"] for m in model.calls] == [False, True]


async def test_verifier_is_not_called_when_no_criterion_needs_a_call() -> None:
    verifier = FakeVerifier()
    chat_only = CRITERIA["05"].model_copy(update={"channel": "chat", "na": True})
    out = await evaluator(FakeModel(), verifier).evaluate(CALL, CHECKLIST, [chat_only])
    assert (verifier.criteria, out.verifier_calls, out.verifier_usd) == ([], 0, 0.0)


async def test_dialog_without_transcript_raises_before_any_call() -> None:
    model = FakeModel()
    empty = CHAT.model_copy(update={"lines": None})
    with pytest.raises(ValueError, match="p1-ru-022"):
        await evaluator(model, FakeVerifier()).evaluate(empty, CHECKLIST, CHECKLIST.criteria)
    assert model.calls == []


async def test_unavailable_model_on_one_criterion_drops_only_it() -> None:
    model = FakeModel({"06": [ModelUnavailable("HTTP 429")]})
    out = await evaluator(model).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)
    assert [e.cid for e in out.results] == ["01", "02", "03", "04", "05", "07", "08"]


async def test_unavailable_flag_question_keeps_found_violation_and_marks_flag() -> None:
    paid = {"reason_ru": "Предложил", "turn_ids": [6], "quote": "Готовые портфели", "violation_found": True}
    model = FakeModel({"08:paid": [paid], "08:leak": [ModelUnavailable("HTTP 429")]})
    [flag] = (await evaluator(model).evaluate(CHAT, CHECKLIST, [FLAG])).results
    assert flag.result.a == {"insult": False, "paid": True, "leak": False}
    assert (flag.result.ev, flag.result.evFail, flag.result.calls) == ([6], True, 2)


async def test_unavailable_model_on_every_call_fails_the_dialog() -> None:
    class Down(FakeModel):
        async def complete(self, messages: list[Message]) -> Reply:
            self.calls.append(messages)
            raise ModelUnavailable("HTTP 503: нет связи")

    with pytest.raises(ModelUnavailable, match="503"):
        await evaluator(Down()).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)


# --- Звук звонка: блок наблюдений после </dialog>, только у звонка с разбором интонации ---

SOUND = {"summary": ["Клиент повысил тон в реплике 3"]}


class Prosody:
    """Разбор интонации по id диалога; исключение — как NotFound или Upstream у dialog_prosody."""

    def __init__(self, body: dict[str, Any] | Exception) -> None:
        self.body = body
        self.asked: list[str] = []

    async def __call__(self, dialog_id: str) -> dict[str, Any]:
        self.asked.append(dialog_id)
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def with_sound(
    model: FakeModel, prosody: Prosody, verifier: FakeVerifier | None = None, *, sends_real_data: bool = False
) -> LlmEvaluator:
    return LlmEvaluator(
        model,
        model_name="qwen3-6",
        reasoning="on",
        anonymize=False,
        verifier=verifier,
        sends_real_data=sends_real_data,
        allow_real_data=False,
        prosody=prosody,
    )


class TextVerifier(FakeVerifier):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict:
        self.texts.append(dialog_text)
        return await super().verify(dialog_text, rules, criteria)


async def test_chat_request_is_byte_identical_and_never_asks_for_sound() -> None:
    plain, sounded, prosody = FakeModel(), FakeModel(), Prosody(SOUND)
    await evaluator(plain).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)
    await with_sound(sounded, prosody).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)
    assert sounded.calls == plain.calls
    assert prosody.asked == []


async def test_call_without_sound_analysis_is_byte_identical() -> None:
    plain = FakeModel()
    await evaluator(plain).evaluate(CALL, CHECKLIST, CHECKLIST.criteria)
    for missing in (NotFound("нет записи"), Upstream("запись не получена"), OSError("нет ffmpeg")):
        sounded, prosody = FakeModel(), Prosody(missing)
        await with_sound(sounded, prosody).evaluate(CALL, CHECKLIST, CHECKLIST.criteria)
        assert (sounded.calls, prosody.asked) == (plain.calls, [CALL.id])


async def test_call_with_sound_analysis_gets_the_block_after_the_dialog() -> None:
    model, verifier, prosody = FakeModel(), TextVerifier(), Prosody(SOUND)
    await with_sound(model, prosody, verifier).evaluate(CALL, CHECKLIST, CHECKLIST.criteria)
    block = sound_block(SOUND)
    assert model.calls and all(f"</dialog>\n\n{block}\n\n" in m[1]["content"] for m in model.calls)
    assert all(m[0]["content"].startswith(SYSTEM_PROMPT) for m in model.calls)
    assert verifier.texts == [f"{render_dialog(CALL)}\n\n{block}"]
    assert prosody.asked == [CALL.id]


async def test_blocked_real_call_never_asks_for_sound() -> None:
    prosody = Prosody(SOUND)
    with pytest.raises(RealDataBlocked):
        await with_sound(FakeModel(), prosody, sends_real_data=True).evaluate(
            CALL, CHECKLIST, CHECKLIST.criteria
        )
    assert prosody.asked == []


async def test_jev_only_mode_gets_the_block_on_calls_only() -> None:
    def jev(verifier: TextVerifier, prosody: Prosody) -> JevEvaluator:
        return JevEvaluator(
            verifier,
            model_name="jev-latest",
            anonymize=False,
            sends_real_data=False,
            allow_real_data=False,
            prosody=prosody,
        )

    verifier, prosody = TextVerifier(), Prosody(SOUND)
    await jev(verifier, prosody).evaluate(CHAT, CHECKLIST, CHECKLIST.criteria)
    await jev(verifier, prosody).evaluate(CALL, CHECKLIST, CHECKLIST.criteria)
    assert verifier.texts == [render_dialog(CHAT), f"{render_dialog(CALL)}\n\n{sound_block(SOUND)}"]
