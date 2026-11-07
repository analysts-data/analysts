"""JevVerifier: один запрос на диалог, choice на критерий, noul на подвопрос флага."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from cqa.adapters.jev import JEV_PRICE_IN, JEV_URL, JevVerifier
from cqa.domain.models import Checklist

KEY = "jev-test-key"
DIALOG_TEXT = "[1 · 00:01] client: Алло.\n[2 · 00:05] operator: Здравствуйте!"
_EMPTY_OK = {"answers": {}, "usage": {"input_tokens": 0}}


def _checklist() -> Checklist:
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "checklist_v3.json").read_text(encoding="utf-8")
    )
    return Checklist.model_validate(raw)


async def _verify(mock_body: dict, *, max_parallel: int = 8):
    checklist = _checklist()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(JEV_URL).respond(200, json=mock_body)
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
        assert "Оцени по dialog только реплики оператора" in question["text"]
    raw = json.dumps(body, ensure_ascii=False)
    for criterion in checklist.criteria:
        assert criterion.name not in raw
        assert criterion.id not in questions


async def test_choice_options_follow_criterion_type_and_na_permission():
    _, body, _ = await _verify(_EMPTY_OK)
    questions = body["questions"]
    for i, criterion in enumerate(_checklist().criteria):
        if criterion.type == "flag":
            continue
        options = questions[f"q{i}"]["options"]
        if criterion.type == "scale":
            assert options == {
                **{str(s): (criterion.stepText or {})[str(s)] for s in criterion.steps or []},
                **({"na": criterion.naCond} if criterion.na else {}),
            }
        else:
            assert options == ["yes", "no"] + (["na"] if criterion.na else [])


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
