"""Оценка диалога: вызов модели на критерий и на подвопрос флага (design.md, п. 1, 8–10, 20)."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from cqa.domain.answer import check, merge_flag, parse_answer, to_result
from cqa.domain.models import (
    Checklist,
    Criterion,
    CriterionResult,
    Dialog,
    DialogEvaluation,
    Evaluation,
    Line,
)
from cqa.domain.prompt import Message, build_messages, render_dialog


@dataclass(frozen=True)
class Reply:
    text: str
    cost: float
    ms: int


class ChatModel(Protocol):
    async def complete(self, messages: list[Message]) -> Reply: ...


@dataclass(frozen=True)
class Verdict:
    answers: dict[str, str | int | dict[str, bool]]  # id критерия → ответ той же формы, что a
    cost: float


class Verifier(Protocol):
    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict: ...


class RealDataBlocked(Exception):
    pass


@dataclass
class _Usage:
    """Вызовы основной модели по одному критерию: число, цена, сумма длительностей HTTP."""

    calls: int = 0
    cost: float = 0.0
    ms: int = 0


class LlmEvaluator:
    """Реализует ports.Evaluator."""

    def __init__(
        self,
        model: ChatModel,
        *,
        model_name: str,
        reasoning: Literal["on", "off"],
        anonymize: bool,
        verifier: Verifier | None,
        sends_real_data: bool,
        allow_real_data: bool,
        config_error: str | None = None,
    ) -> None:
        self.model = model
        self.model_name = model_name
        self.reasoning = reasoning
        self.anonymize = anonymize
        self.verifier = verifier
        self.sends_real_data = sends_real_data
        self.allow_real_data = allow_real_data
        self.config_error = config_error

    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        text = render_dialog(dialog)
        lines = {x.n: x.text for x in dialog.lines or [] if isinstance(x, Line)}
        results = await asyncio.gather(
            *(self._criterion(build_messages(text, checklist.rules, c), c, lines) for c in criteria)
        )
        return DialogEvaluation(
            results=[Evaluation(c.id, r) for c, r in zip(criteria, results, strict=True) if r is not None],
            verifier_calls=0,
            verifier_usd=0.0,
        )

    async def _criterion(
        self, calls: list[list[Message]], criterion: Criterion, lines: Mapping[int, str]
    ) -> CriterionResult | None:
        usage = _Usage()
        if criterion.type == "flag":
            subs = await asyncio.gather(*(self._ask(m, criterion, lines, usage, sub=True) for m in calls))
            return merge_flag(criterion, list(subs), model=self.model_name, **asdict(usage))
        raw, ev_fail = await self._ask(calls[0], criterion, lines, usage, sub=False)
        if raw is None:
            return None
        return to_result(raw, criterion, ev_fail=ev_fail, model=self.model_name, **asdict(usage))

    async def _ask(
        self,
        messages: list[Message],
        criterion: Criterion,
        lines: Mapping[int, str],
        usage: _Usage,
        *,
        sub: bool,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Ответ модели и признак evFail; None — допустимого ответа нет."""
        reply = await self.model.complete(messages)
        usage.calls += 1
        usage.cost += reply.cost
        usage.ms += reply.ms
        raw = parse_answer(reply.text)
        if raw is not None and not check(raw, criterion, lines, sub=sub):
            return raw, False
        return None, False
