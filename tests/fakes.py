"""Fakes for the cross-track ports (design/ports.md). No network."""

import asyncio
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cqa.domain.agreement import Disagreement, Report, TagStats
from cqa.domain.models import (
    Checklist,
    Criterion,
    CriterionResult,
    Dialog,
    DialogEvaluation,
    Evaluation,
    IngestResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


def prototype_checklist() -> Checklist:
    """Checklist v3 of the prototype (CL0) with the general rules."""
    return Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text(encoding="utf-8"))


def prototype_dialogs() -> list[Dialog]:
    """The ten synthetic dialogs of the prototype, with their `res`."""
    raw = json.loads((FIXTURES / "dialogs_prototype.json").read_text(encoding="utf-8"))
    return [Dialog.model_validate(d) for d in raw]


class FakeSource:
    def __init__(
        self,
        dialogs: Sequence[Dialog] = (),
        *,
        audio: Mapping[str, str] | None = None,
        errors: Sequence[str] = (),  # skipped == len(errors), as in IngestResult
        raises: Mapping[str, Exception] | None = None,  # method name -> exception to raise
    ) -> None:
        self.result = IngestResult(list(dialogs), dict(audio or {}), len(errors), list(errors))
        self.raises = dict(raises or {})
        self.fetched: list[tuple[str, str | None]] = []  # (group_id, url) of every fetch

    def _maybe_raise(self, method: str) -> None:
        if method in self.raises:
            raise self.raises[method]

    async def fetch(self, group_id: str, url: str | None = None) -> IngestResult:
        self.fetched.append((group_id, url))
        self._maybe_raise("fetch")
        return self.result

    def upload(self, raw: bytes) -> IngestResult:
        self._maybe_raise("upload")
        return self.result

    async def audio_link(self, audio_url: str) -> str | None:
        self._maybe_raise("audio_link")
        return "https://storage.test/rec.mp3"


def _default_answer(c: Criterion) -> CriterionResult:
    if c.type == "scale":
        return CriterionResult(a=max(c.steps or [0]))
    if c.type == "flag":
        return CriterionResult(a={q.k: False for q in c.questions or []})
    return CriterionResult(a="yes")


class FakeEvaluator:
    """Answers from `res` (default: the prototype fixture), "yes" / max step / no flags otherwise.

    Every result costs one call and 0.001 USD.
    """

    def __init__(
        self,
        *,
        res: Mapping[str, Mapping[str, CriterionResult]] | None = None,
        verifier_calls: int = 0,
        verifier_usd: float = 0.0,
        fail_on: Iterable[str] = (),  # dialog ids -> RuntimeError("timeout")
        skip: Iterable[str] = (),  # cids left without an answer
        gate: asyncio.Event | None = None,  # evaluate waits for it
    ) -> None:
        self.res = res if res is not None else {d.id: d.res for d in prototype_dialogs()}
        self.verifier_calls = verifier_calls
        self.verifier_usd = verifier_usd
        self.fail_on = set(fail_on)
        self.skip = set(skip)
        self.gate = gate
        self.calls = 0
        self.order: list[str] = []
        self.seen: list[str] = []

    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        self.calls += 1
        self.order.append(dialog.id)
        self.seen.extend(c.id for c in criteria)
        if dialog.id in self.fail_on:  # at once, without waiting for the gate
            raise RuntimeError("timeout")
        if self.gate is not None:
            await self.gate.wait()
        known = self.res.get(dialog.id, {})
        results = [
            Evaluation(
                c.id, (known.get(c.id) or _default_answer(c)).model_copy(update={"calls": 1, "cost": 0.001})
            )
            for c in criteria
            if c.id not in self.skip
        ]
        return DialogEvaluation(results, self.verifier_calls, self.verifier_usd)


MODEL_REASON = "синтетическое обоснование модели"


def eval_report_body(**over: Any) -> dict[str, Any]:
    """Синтетическое тело eval/reports/<stamp>.json, как его пишет make eval: без реальных диалогов."""
    report = Report(
        agree_total=0.9,
        per_lang={"RU": 0.92, "KZ": 0.85},
        per_cid={"c1": 1.0, "c2": 0.8},
        missing=1,
        kz_gap_pts=7.0,
        gross_recall={"k1": 1.0, "k2": 0.5},
        gross_recall_lang={"RU": 0.5},
        gross_missed=[("dlg-2", "k2")],
        na_precision=0.95,
        na_recall=None,
        stability=0.97,
        evidence_ok=0.99,
        cost=0.12,
        calls=40,
        seconds=31.0,
        n_dialogs=4,
        model="model-x",
        false_flags=2,
        tags=TagStats(recurring=3, single=1),
        disagreements=[
            Disagreement("dlg-1", "c2", ["yes"], "no", MODEL_REASON, "синтетическая цитата"),
            Disagreement("dlg-2", "c3", [{"k1": False, "k2": True}], None, None, None),
        ],
    )
    extra = {"cost_per_dialog": 0.03, "calls_per_dialog": 10.0, "problems": ["замечание"]}
    return asdict(report) | extra | over
