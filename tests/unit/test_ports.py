from collections.abc import Sequence
from pathlib import Path

import pytest
from mypy import api as mypy_api

from cqa.domain.models import (
    Checklist,
    Criterion,
    CriterionResult,
    Dialog,
    DialogEvaluation,
    Evaluation,
    IngestResult,
    Mode,
)
from cqa.services.errors import ConfigError, Conflict, Invalid, NotFound, Unavailable, Upstream
from cqa.services.ports import DialogSource, Evaluator

ROOT = Path(__file__).resolve().parents[2]


class StubSource:
    async def fetch(self, group_id: str, url: str | None = None) -> IngestResult:
        return IngestResult(dialogs=[], audio={}, skipped=0, errors=[])

    def upload(self, raw: bytes) -> IngestResult:
        return IngestResult(dialogs=[], audio={}, skipped=1, errors=["syn-1: не JSON"])

    async def audio_link(self, audio_url: str) -> str | None:
        return None


class StubEvaluator:
    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        results = [Evaluation(cid=c.id, result=CriterionResult(a="na")) for c in criteria]
        return DialogEvaluation(results=results, verifier_calls=0, verifier_usd=0.0)


source: DialogSource = StubSource()
evaluator: Evaluator = StubEvaluator()


def test_contract_mode_example_round_trips() -> None:
    mode = {"where": "kz", "anonymized": True, "model": "qwen3-6", "verifier": "jev"}
    assert Mode.model_validate(mode).model_dump(mode="json") == mode


def test_stubs_satisfy_protocols_under_mypy() -> None:
    out, err, status = mypy_api.run(["--config-file", str(ROOT / "pyproject.toml"), __file__])
    assert status == 0, out + err


async def test_stub_evaluator_answers_each_criterion_in_order() -> None:
    checklist = Checklist.model_validate(
        {"version": 1, "rules": "", "sections": ["s"], "criteria": [_criterion("02"), _criterion("01")]}
    )
    dialog = Dialog(id="d", ch="chat", lang="RU", at="07.11 14:50", lines=[])
    out = await evaluator.evaluate(dialog, checklist, checklist.criteria)
    assert [e.cid for e in out.results] == ["02", "01"]


@pytest.mark.parametrize("cls", [NotFound, Invalid, Conflict, Upstream, Unavailable, ConfigError])
def test_service_errors_keep_their_message(cls: type[Exception]) -> None:
    assert str(cls("Диалог d не найден")) == "Диалог d не найден"


def _criterion(cid: str) -> dict[str, object]:
    return {"id": cid, "sec": 0, "name": "n", "type": "bool", "w": 1, "text": "t"}
