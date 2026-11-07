import asyncio
from pathlib import Path

import pytest
from mypy import api as mypy_api

from cqa.domain.models import Checklist, CriterionResult, Dialog
from cqa.services.errors import Upstream
from cqa.services.ports import DialogSource, Evaluator
from fakes import FakeEvaluator, FakeSource

TESTS = Path(__file__).resolve().parents[1]

source: DialogSource = FakeSource()
evaluator: Evaluator = FakeEvaluator(res={})

CHECKLIST = Checklist.model_validate(
    {
        "version": 3,
        "rules": "",
        "sections": ["s"],
        "criteria": [
            {"id": "01", "sec": 0, "name": "n", "type": "bool", "w": 10, "text": "t"},
            {"id": "04", "sec": 0, "name": "n", "type": "scale", "w": 20, "steps": [20, 15, 0], "text": "t"},
            {"id": "08", "sec": 0, "name": "n", "type": "flag", "w": 0, "text": "t",
             "questions": [{"k": "insult", "label": "l"}, {"k": "leak", "label": "l"}]},
        ],
    }
)  # fmt: skip
DIALOG = Dialog(id="call-024", ch="call", lang="RU", at="07.11 14:52", lines=[])


def test_fakes_satisfy_protocols_under_mypy() -> None:
    files = [str(TESTS / "fakes.py"), __file__]
    out, err, status = mypy_api.run(["--config-file", str(TESTS.parent / "pyproject.toml"), *files])
    assert status == 0, out + err


async def test_fake_source_returns_configured_result_or_raises() -> None:
    fake = FakeSource([DIALOG], audio={"call-024": "https://storage.test/sig"}, errors=["syn-1: нет id"])
    result = await fake.fetch("DEV")
    assert (result.dialogs, result.audio, result.skipped) == (
        [DIALOG],
        {"call-024": "https://storage.test/sig"},
        1,
    )
    assert fake.upload(b"{}") == result
    assert await fake.audio_link("x") == "https://storage.test/rec.mp3"
    with pytest.raises(Upstream, match="не ответил"):
        await FakeSource(raises={"fetch": Upstream("API не ответил")}).fetch("DEV")


async def test_fake_evaluator_answers_known_pairs_and_defaults_the_rest() -> None:
    fake = FakeEvaluator(
        res={"call-024": {"04": CriterionResult(a=15, alt=10)}}, verifier_calls=1, verifier_usd=0.0002
    )
    out = await fake.evaluate(DIALOG, CHECKLIST, CHECKLIST.criteria)
    answers = {e.cid: e.result.a for e in out.results}
    assert answers == {"01": "yes", "04": 15, "08": {"insult": False, "leak": False}}
    assert all(e.result.calls == 1 and e.result.cost == 0.001 for e in out.results)
    assert (out.verifier_calls, out.verifier_usd) == (1, 0.0002)
    assert (fake.calls, fake.order, fake.seen) == (1, ["call-024"], ["01", "04", "08"])


async def test_fake_evaluator_skips_fails_and_waits_for_gate() -> None:
    gate = asyncio.Event()
    fake = FakeEvaluator(res={}, skip={"04"}, fail_on={"p1-ru-003"}, gate=gate)
    task = asyncio.create_task(fake.evaluate(DIALOG, CHECKLIST, CHECKLIST.criteria))
    await asyncio.sleep(0)
    assert not task.done()
    gate.set()
    assert [e.cid for e in (await task).results] == ["01", "08"]
    with pytest.raises(RuntimeError, match="timeout"):
        await fake.evaluate(DIALOG.model_copy(update={"id": "p1-ru-003"}), CHECKLIST, CHECKLIST.criteria)
