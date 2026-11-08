"""Оценка диалога: вызов модели на критерий и на подвопрос флага (design.md, п. 1, 8–10, 16–20)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from cqa.domain.anonymize import anonymize
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
from cqa.domain.prompt import Message, build_messages, render_dialog, sound_block
from cqa.services.errors import ConfigError


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
    confidence: dict[str, float] = field(default_factory=dict)  # id → вероятность ответа, у флага наименьшая


class Verifier(Protocol):
    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict: ...


# id звонка → тело `GET /prosody` (dialog_prosody); исключение — разбора нет, звонок оценивается по тексту
Prosody = Callable[[str], Awaitable[Mapping[str, Any]]]


class RealDataBlocked(Exception):
    pass


class ModelUnavailable(Exception):
    """Провайдер не ответил или вернул ошибку после всех повторов (бросает любая ChatModel)."""


_NO_JSON = {False: "нет объекта JSON с полем answer", True: "нет объекта JSON с полем violation_found"}

_LOG = logging.getLogger(__name__)


def _apply_verdict(criterion: Criterion, result: CriterionResult, answer: Any) -> None:
    """alt и правило флага «нашла любая модель»; нет ответа Jev на подвопрос — evFail."""
    if answer is None:
        if criterion.type == "flag":
            result.evFail = True  # нет ответа ни по одному подвопросу: флаг на проверку
        return
    result.alt = answer
    if criterion.type != "flag" or not isinstance(answer, dict):
        return
    questions = criterion.questions or []
    current = result.a
    if not isinstance(current, dict):
        return
    only_jev = [q.label for q in questions if answer.get(q.k) and not current.get(q.k)]
    result.a = {k: bool(current.get(k)) or bool(answer.get(k)) for k in current}
    if any(q.k not in answer for q in questions):
        result.evFail = True
    if only_jev:
        notes = "; ".join(
            f"Нарушение «{label}» нашло только второе мнение, основная модель его не подтвердила."
            for label in only_jev
        )
        result.why = f"{result.why}; {notes}" if result.why else notes


def _with(text: str, sound: str | None) -> str:
    """Текст диалога для Jev: у него нет </dialog>, блок звука идёт следом за репликами."""
    return f"{text}\n\n{sound}" if sound else text


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


class _Gate:
    """Общее для оценщиков: ошибка конфигурации, запрет реальных звонков, обезличивание, другой канал."""

    model_name: str
    anonymize: bool
    sends_real_data: bool
    allow_real_data: bool
    config_error: str | None
    prosody: Prosody | None

    async def _sound(self, dialog: Dialog) -> str | None:
        """Блок звука звонка; чат, нет порта или разбора (нет записи, сети, ffmpeg) — None, запрос прежний."""
        if dialog.ch != "call" or self.prosody is None:
            return None
        try:
            return sound_block(await self.prosody(dialog.id))
        except Exception as exc:  # интонация не роняет оценку
            _LOG.info("Диалог %s: без звука: %s: %s", dialog.id, type(exc).__name__, exc)
            return None

    def _admit(self, dialog: Dialog) -> Dialog:
        """Диалог, который можно отправить модели; иначе ConfigError, ValueError или RealDataBlocked."""
        if self.config_error:
            raise ConfigError(self.config_error)
        if dialog.lines is None:
            raise ValueError(f"Расшифровка диалога {dialog.id} не загружена")
        # реальный звонок уходит наружу только с разрешения человека (design.md п. 19)
        if dialog.ch == "call" and self.sends_real_data and not self.allow_real_data:
            raise RealDataBlocked(
                f"Диалог {dialog.id}: реальный звонок можно отправлять модели только с CQA_ALLOW_REAL_DATA=1"
            )
        return anonymize(dialog) if self.anonymize else dialog

    def _other_channel(self) -> CriterionResult:
        return CriterionResult(
            a="na", why="Критерий для другого канала", model=self.model_name, calls=0, cost=0, ms=0
        )


class LlmEvaluator(_Gate):
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
        prosody: Prosody | None = None,
    ) -> None:
        self.model = model
        self.model_name = model_name
        self.reasoning = reasoning
        self.anonymize = anonymize
        self.verifier = verifier
        self.sends_real_data = sends_real_data
        self.allow_real_data = allow_real_data
        self.config_error = config_error
        self.prosody = prosody

    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        dialog = self._admit(dialog)
        assert dialog.lines is not None  # проверено в _admit, anonymize список реплик не меняет
        text, sound = render_dialog(dialog), await self._sound(dialog)
        lines = {x.n: x.text for x in dialog.lines if isinstance(x, Line)}
        # канал решает код: критерий другого канала не идёт ни к модели, ни ко второму мнению
        asked = [c for c in criteria if c.channel in ("all", dialog.ch)]
        prompts = [build_messages(text, checklist.rules, c, dialog.ch, sound) for c in asked]
        failures: list[tuple[str, ModelUnavailable]] = []
        found_future = asyncio.gather(
            *(self._criterion(m, c, lines, failures) for m, c in zip(prompts, asked, strict=True))
        )
        verdict: Verdict | None = None
        if self.verifier and asked:
            try:
                verdict = await self.verifier.verify(_with(text, sound), checklist.rules, asked)
            except Exception as exc:  # сбой второго мнения не рушит оценку и не попадает в результаты
                _LOG.warning("Второе мнение не ответило: %s: %s", type(exc).__name__, exc)
        found = await found_future
        for cid, err in failures:
            _LOG.warning("Диалог %s, критерий %s: модель недоступна: %s", dialog.id, cid, err)
        if failures and len(failures) == sum(map(len, prompts)):
            raise failures[0][1]  # провайдер недоступен совсем: сбой всего диалога
        by_id = dict(zip((c.id for c in asked), found, strict=True))
        results = []
        for c in criteria:
            result = by_id[c.id] if c.id in by_id else self._other_channel()
            if result is not None:  # None: допустимого ответа нет, критерий ждёт оценки
                if verdict is not None and c.id in by_id:
                    _apply_verdict(c, result, verdict.answers.get(c.id))
                results.append(Evaluation(c.id, result))
        return DialogEvaluation(
            results=results,
            verifier_calls=1 if verdict else 0,
            verifier_usd=verdict.cost if verdict else 0.0,
        )

    async def _criterion(
        self,
        calls: list[list[Message]],
        criterion: Criterion,
        lines: Mapping[int, str],
        failures: list[tuple[str, ModelUnavailable]],
    ) -> CriterionResult | None:
        usage = _Usage()
        sub = criterion.type == "flag"

        async def ask(messages: list[Message]) -> tuple[dict[str, Any] | None, bool]:
            try:
                return await self._ask(messages, criterion, lines, usage, sub=sub)
            except ModelUnavailable as exc:  # подвопрос — «не найдено» с evFail, критерий — ждёт оценки
                failures.append((criterion.id, exc))
                return None, False

        if sub:
            subs = await asyncio.gather(*map(ask, calls))
            return merge_flag(criterion, list(subs), model=self.model_name, **asdict(usage))
        raw, ev_fail = await ask(calls[0])
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


JEV_SURE = 0.6  # ponytail: порог не подобран на эталоне; ниже — evFail, ответ в «Нужна проверка»


def _jev_why(p: float | None) -> str:
    """Честное обоснование без причин: Jev отдаёт только ответ и вероятность."""
    if p is None:
        return "Jev не вернул вероятность ответа, нужна проверка; модель не пишет обоснований"
    low = f" — ниже порога {JEV_SURE:.1f}, нужна проверка" if p < JEV_SURE else ""
    return f"Ответ Jev с вероятностью {p:.2f}{low}".replace(".", ",") + "; модель не пишет обоснований"


class JevEvaluator(_Gate):
    """Реализует ports.Evaluator только на Jev: один запрос на диалог, без обоснований и оснований."""

    def __init__(
        self,
        jev: Verifier,
        *,
        model_name: str,
        anonymize: bool,
        sends_real_data: bool,
        allow_real_data: bool,
        config_error: str | None = None,
        prosody: Prosody | None = None,
    ) -> None:
        self.jev = jev
        self.model_name = model_name
        self.anonymize = anonymize
        self.sends_real_data = sends_real_data
        self.allow_real_data = allow_real_data
        self.config_error = config_error
        self.prosody = prosody

    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        dialog = self._admit(dialog)
        asked = [c for c in criteria if c.channel in ("all", dialog.ch)]
        verdict, ms = Verdict(answers={}, cost=0.0), 0
        if asked:  # сбой Jev — сбой всего диалога, как у основной модели
            text = _with(render_dialog(dialog), await self._sound(dialog))
            start = time.monotonic()
            verdict = await self.jev.verify(text, checklist.rules, asked)
            ms = round((time.monotonic() - start) * 1000)
        found = {c.id: r for c in asked if (r := self._result(c, verdict, ms)) is not None}
        # один запрос на все ответы: calls = 1 у первого, цена запроса поровну
        for i, r in enumerate(found.values()):
            r.calls, r.cost = int(i == 0), verdict.cost / len(found)
        results = [
            Evaluation(c.id, found[c.id] if c.id in found else self._other_channel())
            for c in criteria
            if c.id in found or c.channel not in ("all", dialog.ch)
        ]
        return DialogEvaluation(results=results, verifier_calls=0, verifier_usd=0.0)

    def _result(self, criterion: Criterion, verdict: Verdict, ms: int) -> CriterionResult | None:
        """Ответ Jev в CriterionResult; нет ответа по критерию — None (ждёт оценки), флаг — всегда."""
        answer: Any = verdict.answers.get(criterion.id)  # форма a: Verdict уже отсеял чужие значения
        p = verdict.confidence.get(criterion.id)
        unsure = p is None or p < JEV_SURE
        if criterion.type == "flag":
            given = answer if isinstance(answer, dict) else {}
            questions = criterion.questions or []
            answer = {q.k: bool(given.get(q.k)) for q in questions}
            unsure = unsure or any(q.k not in given for q in questions)  # нет ответа — «не найдено»
        elif answer is None:
            return None
        return CriterionResult(a=answer, why=_jev_why(p), evFail=unsure, model=self.model_name, ms=ms)
