"""Оценка диалога: вызов модели на критерий и на подвопрос флага (design.md, п. 1, 8–10, 20)."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from cqa.domain.answer import allowed_answer, check, merge_flag, parse_answer, to_result
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


_NO_JSON = {False: "нет объекта JSON с полем answer", True: "нет объекта JSON с полем violation_found"}


def _allowed(raw: dict[str, Any], criterion: Criterion, sub: bool) -> bool:
    if sub:
        return isinstance(raw.get("violation_found"), bool)
    return allowed_answer(raw, criterion) is not None


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
        if dialog.lines is None:
            raise ValueError(f"Расшифровка диалога {dialog.id} не загружена")
        text = render_dialog(dialog)
        lines = {x.n: x.text for x in dialog.lines if isinstance(x, Line)}
        # канал решает код: критерий другого канала не идёт ни к модели, ни ко второму мнению
        asked = [c for c in criteria if c.channel in ("all", dialog.ch)]
        answers = asyncio.gather(
            *(self._criterion(build_messages(text, checklist.rules, c), c, lines) for c in asked)
        )
        verdict: Verdict | None = None
        if self.verifier and asked:
            found, verdict = await asyncio.gather(answers, self.verifier.verify(text, checklist.rules, asked))
        else:
            found = await answers
        by_id = dict(zip((c.id for c in asked), found, strict=True))
        results = []
        for c in criteria:
            result = by_id[c.id] if c.id in by_id else self._other_channel()
            if result is not None:  # None: допустимого ответа нет, критерий ждёт оценки
                results.append(Evaluation(c.id, result))
        return DialogEvaluation(
            results=results,
            verifier_calls=1 if verdict else 0,
            verifier_usd=verdict.cost if verdict else 0.0,
        )

    def _other_channel(self) -> CriterionResult:
        return CriterionResult(
            a="na", why="Критерий для другого канала", model=self.model_name, calls=0, cost=0, ms=0
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
        """Ответ и признак evFail: один повтор с текстом ошибок; None — допустимого ответа нет."""
        reply = await self._complete(messages, usage)
        first = parse_answer(reply.text)
        errors = check(first, criterion, lines, sub=sub) if first else [_NO_JSON[sub]]
        if not errors:
            return first, False
        fix = f"Ответ не прошёл проверку: {'; '.join(errors)}. Исправь и верни один объект JSON целиком."
        retry: list[Message] = [
            *messages,
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content": fix},
        ]
        second = parse_answer((await self._complete(retry, usage)).text)
        if second and not check(second, criterion, lines, sub=sub):
            return second, False
        allowed = next((r for r in (second, first) if r and _allowed(r, criterion, sub)), None)
        return allowed, allowed is not None

    async def _complete(self, messages: list[Message], usage: _Usage) -> Reply:
        reply = await self.model.complete(messages)
        usage.calls += 1
        usage.cost += reply.cost
        usage.ms += reply.ms
        return reply
