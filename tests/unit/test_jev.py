"""JevVerifier: один запрос на диалог, choice на критерий, noul на подвопрос флага."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from cqa.adapters.jev import JEV_PRICE_IN, JEV_URL, JevVerifier
from cqa.domain.models import Checklist, Dialog, JevQuestion, Line
from cqa.services.evaluation import LlmEvaluator, Reply

KEY = "jev-test-key"
DIALOG_TEXT = "[1 · 00:01] client: Алло.\n[2 · 00:05] operator: Здравствуйте!"
_EMPTY_OK = {"answers": {}, "usage": {"input_tokens": 0}}


def v1(answers: dict) -> dict:
    """Ответы в форме API v1: choice — {"choice": ключ criteria}, noul — {"noul": вероятность}."""
    out = {}
    for key, value in answers.items():
        if "_" in key:
            out[key] = {"type": "noul", "noul": value}
        else:
            choice = str(value)
            out[key] = {"type": "choice", "choice": choice, "confidence": 0.9, "probabilities": {choice: 0.9}}
    return out


def _checklist() -> Checklist:
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "checklist_v3.json").read_text(encoding="utf-8")
    )
    return Checklist.model_validate(raw)


async def _verify(mock_body: dict, *, max_parallel: int = 8):
    checklist = _checklist()
    with respx.mock(assert_all_called=False) as mock:
        body = {**mock_body, "answers": v1(mock_body.get("answers", {}))}
        route = mock.post(JEV_URL).respond(200, json=body)
        async with httpx.AsyncClient() as http:
            verdict = await JevVerifier(KEY, http, max_parallel=max_parallel).verify(
                DIALOG_TEXT, checklist.rules, checklist.criteria
            )
    assert route.call_count == 1
    return checklist, json.loads(route.calls[0].request.content), verdict


async def test_request_has_positional_choice_and_noul_questions_without_identifiers():
    checklist, body, _ = await _verify(_EMPTY_OK)
    assert body["model"] == "jev-latest"
    assert body["state"] == {"rules": checklist.rules, "dialog": DIALOG_TEXT}
    questions = body["questions"]
    flag = next(c for c in checklist.criteria if c.type == "flag")
    flag_at = checklist.criteria.index(flag)
    expected = [f"q{i}" for i, c in enumerate(checklist.criteria) if c is not flag]
    expected += [f"q{flag_at}_{j}" for j in range(len(flag.questions or []))]
    assert list(questions) == expected
    choice = [q for q in questions.values() if q["type"] == "choice"]
    noul = [q for q in questions.values() if q["type"] == "noul"]
    assert len(choice) == 7
    assert len(noul) == 3
    for question in questions.values():
        assert "Оцени по dialog только реплики оператора" in question["instructions"]
        assert "text" not in question and "options" not in question
    raw = json.dumps(body, ensure_ascii=False)
    for criterion in checklist.criteria:
        assert criterion.name not in raw
        assert criterion.id not in questions


async def test_choice_criteria_follow_criterion_type_and_na_permission():
    _, body, _ = await _verify(_EMPTY_OK)
    questions = body["questions"]
    for i, criterion in enumerate(_checklist().criteria):
        if criterion.type == "flag":
            continue
        criteria = questions[f"q{i}"]["criteria"]
        na = {"na": criterion.naCond} if criterion.na else {}
        if criterion.type == "scale":
            assert criteria == {
                **{str(s): (criterion.stepText or {})[str(s)] for s in criterion.steps or []},
                **na,
            }
        else:
            assert criteria == {"yes": "Да", "no": "Нет", **na}


async def test_choice_criteria_take_answer_descriptions_from_jev():
    checklist = _checklist()
    base = next(c for c in checklist.criteria if c.type == "bool" and c.na)
    jev = JevQuestion(
        type="choice",
        instructions=base.text,
        criteria={"yes": "Да, назвал", "no": "Не назвал", "not_applicable": "Срока нет"},
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JEV_URL).respond(200, json=_EMPTY_OK)
        async with httpx.AsyncClient() as http:
            await JevVerifier(KEY, http).verify(
                DIALOG_TEXT, checklist.rules, [base.model_copy(update={"jev": jev})]
            )
    criteria = json.loads(route.calls[0].request.content)["questions"]["q0"]["criteria"]
    assert criteria == {"yes": "Да, назвал", "no": "Не назвал", "na": "Срока нет"}


async def test_request_carries_bearer_authorization():
    checklist = _checklist()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JEV_URL).respond(200, json=_EMPTY_OK)
        async with httpx.AsyncClient() as http:
            await JevVerifier(KEY, http).verify(DIALOG_TEXT, checklist.rules, checklist.criteria)
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {KEY}"


async def test_answers_become_verdict_in_contract_shape_with_input_token_cost():
    checklist = _checklist()
    ids = [c.id for c in checklist.criteria]
    flag = checklist.criteria[-1]
    sub = {q.k: given for q, given in zip(flag.questions or [], [0.83, 0.2, 0.9], strict=True)}
    raw = {
        "answers": {
            "q0": "yes",
            "q1": "no",
            "q2": "na",
            "q3": "15",
            "q4": "yes",
            "q5": 10,
            "q7_0": 0.83,
            "q7_1": 0.2,
            "q7_2": 0.9,
        },
        "usage": {"input_tokens": 4000},
    }
    _, _, verdict = await _verify(raw)
    expected = {ids[0]: "yes", ids[1]: "no", ids[2]: "na", ids[3]: 15, ids[4]: "yes", ids[5]: 10}
    expected[flag.id] = {k: v >= 0.5 for k, v in sub.items()}
    assert verdict.answers == expected
    assert verdict.cost == pytest.approx(4000 * JEV_PRICE_IN / 1_000_000) == pytest.approx(0.000168)


async def test_missing_question_key_gives_no_answer_for_that_criterion():
    checklist = _checklist()
    ids = [c.id for c in checklist.criteria]
    raw = {"answers": {"q0": "yes"}, "usage": {"input_tokens": 10}}
    _, _, verdict = await _verify(raw)
    assert verdict.answers == {ids[0]: "yes"}
    assert verdict.cost == pytest.approx(10 * JEV_PRICE_IN / 1_000_000)


async def test_parallel_requests_are_capped_by_semaphore():
    inflight = 0
    peak = 0

    async def handler(request: object) -> httpx.Response:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1
        return httpx.Response(200, json=_EMPTY_OK)

    checklist = _checklist()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(JEV_URL).mock(side_effect=handler)
        async with httpx.AsyncClient() as http:
            verifier = JevVerifier(KEY, http, max_parallel=1)
            await asyncio.gather(
                *(verifier.verify(DIALOG_TEXT, checklist.rules, checklist.criteria) for _ in range(3))
            )
    assert peak == 1


# --- LlmEvaluator с вторым мнением Jev (задача 6.4) ---


class FakeModel:
    """Основная модель: yes на критерии, violation_found по флагу — как задано."""

    def __init__(self, *, violation: bool = False) -> None:
        self.violation = violation

    async def complete(self, messages):
        payload = (
            {
                "reason_ru": "нарушение не найдено",
                "turn_ids": [2],
                "quote": "здравствуйте",
                "checked_range": None,
                "violation_found": self.violation,
            }
            if "Нарушение для проверки" in messages[-1]["content"]
            else {
                "reason_ru": "оператор поздоровался",
                "turn_ids": [2],
                "quote": "здравствуйте",
                "checked_range": None,
                "answer": "yes",
                "tag": "",
                "better": "",
            }
        )
        return Reply(text=json.dumps(payload, ensure_ascii=False), cost=0.001, ms=5)


def _dialog():
    return Dialog(
        id="d1",
        ch="chat",
        lang="RU",
        at="07.11 13:49",
        lines=[
            Line(n=1, t="00:01", who="client", text="алло"),
            Line(n=2, t="00:05", who="operator", text="здравствуйте"),
        ],
    )


def _criteria():
    checklist = _checklist()
    bools = [c for c in checklist.criteria if c.type == "bool"]
    flag = next(c for c in checklist.criteria if c.type == "flag")
    return checklist, bools[:2] + [flag]


def _evaluator(verifier, model=None):
    return LlmEvaluator(
        model or FakeModel(),
        model_name="qwen3-6",
        reasoning="on",
        anonymize=False,
        verifier=verifier,
        sends_real_data=False,
        allow_real_data=False,
    )


async def _evaluate_with_jev(answers: dict, usage: int = 4000, *, violation: bool = False):
    checklist, criteria = _criteria()
    body = {"answers": v1(answers), "usage": {"input_tokens": usage}}
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JEV_URL).respond(200, json=body)
        async with httpx.AsyncClient() as http:
            evaluation = await _evaluator(JevVerifier(KEY, http)).evaluate(_dialog(), checklist, criteria)
    return checklist, criteria, evaluation, route


async def test_alt_written_for_criteria_with_jev_answer_and_price_only_in_verifier_usd():
    _, criteria, evaluation, route = await _evaluate_with_jev(
        {"q0": "no", "q1": "yes", "q2_0": 0.9, "q2_1": 0.1, "q2_2": 0.1}
    )
    ids = [c.id for c in criteria]
    alt = {e.cid: e.result.alt for e in evaluation.results}
    assert alt[ids[0]] == "no"
    assert alt[ids[1]] == "yes"
    flag_alt = alt[criteria[2].id]
    # noul переводится в булево на стороне Jev: alt — ответ второго мнения той же формы, что a
    given = [0.9, 0.1, 0.1]
    assert flag_alt == {q.k: v >= 0.5 for q, v in zip(criteria[2].questions, given, strict=True)}
    # цена Jev только в verifier_usd: у результатов только цена основной модели (флаг — три вызова)
    costs = {e.cid: e.result.cost for e in evaluation.results}
    assert costs == {
        ids[0]: pytest.approx(0.001),
        ids[1]: pytest.approx(0.001),
        criteria[2].id: pytest.approx(0.003),
    }
    assert (
        evaluation.verifier_usd == pytest.approx(4000 * JEV_PRICE_IN / 1_000_000) == pytest.approx(0.000168)
    )
    assert evaluation.verifier_calls == 1
    assert route.call_count == 1


async def test_flag_set_when_only_second_opinion_found_with_note_in_why():
    _, criteria, evaluation, _ = await _evaluate_with_jev(
        {"q0": "yes", "q1": "yes", "q2_0": 0.9, "q2_1": 0.1, "q2_2": 0.1}, violation=False
    )
    flag = criteria[2]
    result = next(e.result for e in evaluation.results if e.cid == flag.id)
    assert result.a == {q.k: found for q, found in zip(flag.questions, [True, False, False], strict=True)}
    assert flag.questions[0].label in (result.why or "")
    assert "нашло только второе мнение" in (result.why or "")


async def test_missing_jev_answer_on_flag_subquestion_sets_evfail():
    _, criteria, evaluation, _ = await _evaluate_with_jev(
        {"q0": "yes", "q1": "yes", "q2_0": 0.1, "q2_2": 0.1}
    )
    flag = criteria[2]
    result = next(e.result for e in evaluation.results if e.cid == flag.id)
    assert result.evFail is True
    assert result.a == {q.k: found for q, found in zip(flag.questions, [False, False, False], strict=True)}


async def test_jev_failure_keeps_results_without_alt_and_without_exception():
    checklist, criteria = _criteria()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JEV_URL).respond(400, json={"error": "long context"})  # без повторов post_json
        async with httpx.AsyncClient() as http:
            evaluation = await _evaluator(JevVerifier(KEY, http), model=FakeModel()).evaluate(
                _dialog(), checklist, criteria
            )
    assert len(evaluation.results) == 3
    assert all(e.result.alt is None for e in evaluation.results)
    assert evaluation.verifier_usd == 0.0
    assert evaluation.verifier_calls == 0
    assert route.call_count == 1


async def test_disabled_verifier_sends_nothing():
    checklist, criteria = _criteria()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JEV_URL).respond(200, json=_EMPTY_OK)
        evaluation = await _evaluator(None).evaluate(_dialog(), checklist, criteria)
    assert all(e.result.alt is None for e in evaluation.results)
    assert evaluation.verifier_calls == 0
    assert evaluation.verifier_usd == 0.0
    assert route.call_count == 0
