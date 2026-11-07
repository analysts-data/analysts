"""Записанные ответы модели на чатах прототипа (llm-evaluation 7.1).

`make record` пишет `tests/cassettes/llm/` сценарием 4, `make check` проигрывает их в `replay`.
Правка промпта, отрисовки или обезличивания меняет тела запросов: тест падает с `CassetteMissing`,
нужен новый `make record` в том же PR.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cqa.compose import build_evaluator
from cqa.domain.models import Checklist, CriterionResult, Dialog, DialogEvaluation
from cqa.settings import Settings

pytestmark = pytest.mark.cassette

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CHECKLIST = Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text(encoding="utf-8"))
CHATS = [
    d
    for d in (
        Dialog.model_validate(x) for x in json.loads((FIXTURES / "dialogs_prototype.json").read_text("utf-8"))
    )
    if d.ch == "chat" and d.lines
]


async def _evaluate_all() -> dict[str, DialogEvaluation]:
    evaluator = build_evaluator(Settings())
    return {d.id: await evaluator.evaluate(d, CHECKLIST, CHECKLIST.criteria) for d in CHATS}


def test_prototype_chats_are_evaluated_from_recorded_answers() -> None:
    # make record гонит этот тест в одной сессии с e2e: синхронный Playwright держит цикл событий в
    # главном потоке, поэтому оценка идёт в своём потоке со своим циклом
    with ThreadPoolExecutor(1) as pool:
        outs = pool.submit(asyncio.run, _evaluate_all()).result()
    assert sorted(outs) == ["p1-ru-003", "p1-ru-022", "p1-ru-025"]
    for out in outs.values():
        assert out.results
        for e in out.results:
            CriterionResult.model_validate(e.result.model_dump())
    flag_id = next(c.id for c in CHECKLIST.criteria if c.type == "flag")
    flag = {e.cid: e.result for e in outs["p1-ru-022"].results}[flag_id]
    assert isinstance(flag.a, dict) and any(flag.a.values())
    assert flag.ev and flag.quote
