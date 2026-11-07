"""Второе мнение Jev: один запрос на диалог, choice на критерий, noul на подвопрос флага."""

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx

from cqa.adapters.llm import post_json
from cqa.domain.models import Criterion
from cqa.services.evaluation import Verdict

JEV_URL = "https://api.typesafe.ai/v1/systemone"
_JEV_MODEL = "jev-latest"
# Цена Jev, USD за 1 млн входных токенов; выход бесплатный (design/ports.md)
JEV_PRICE_IN = 0.042
_MAX_PARALLEL = 8
_INSTRUCTION = (
    "Оцени по dialog только реплики оператора; реплики с пометкой «не оценивается» — контекст; "
    "учитывай rules."
)


def _text(body: str) -> str:
    return f"{_INSTRUCTION}\n\n{body}"


def _choice_options(criterion: Criterion) -> list[str] | dict[str, str]:
    if criterion.type == "scale":
        options = {str(s): (criterion.stepText or {})[str(s)] for s in criterion.steps or []}
        if criterion.na:
            options["na"] = criterion.naCond or ""
        return options
    return ["yes", "no"] + (["na"] if criterion.na else [])


def _choice_answer(value: Any, criterion: Criterion) -> str | int | None:
    """Ответ той же формы, что a: yes/no/na или ступень шкалы; чужое значение — нет ответа."""
    if isinstance(value, bool):
        return None
    if criterion.type == "scale":
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if value == "na":
            return "na" if criterion.na else None
        return value if isinstance(value, int) and value in (criterion.steps or []) else None
    if value in ("yes", "no"):
        return str(value)
    return "na" if value == "na" and criterion.na else None


def _questions(criteria: Sequence[Criterion]) -> dict[str, dict[str, Any]]:
    """Позиционные вопросы q{i} и q{i}_{j}: идентификаторов и названий критериев модель не видит."""
    questions: dict[str, dict[str, Any]] = {}
    for i, criterion in enumerate(criteria):
        if criterion.type == "flag":
            for j, question in enumerate(criterion.questions or []):
                questions[f"q{i}_{j}"] = {"type": "noul", "text": _text(question.text or question.label)}
            continue
        questions[f"q{i}"] = {
            "type": "choice",
            "text": _text(criterion.text),
            "options": _choice_options(criterion),
        }
    return questions


def _found(value: Any) -> bool:
    """noul: доля 0..1, порог 0,5 (замер: 8 из 8 без ложных флагов); чужое значение — не найдено."""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return False
    return bool(value >= 0.5) if isinstance(value, int | float) else False


def _answers(raw: dict[str, Any], criteria: Sequence[Criterion]) -> dict[str, str | int | dict[str, bool]]:
    """Ключи ответа q{i} и q{i}_{j} обратно в id критерия; нет ключа — нет ответа."""
    answers: dict[str, str | int | dict[str, bool]] = {}
    for i, criterion in enumerate(criteria):
        if criterion.type == "flag":
            flags = {
                question.k: _found(raw[f"q{i}_{j}"])
                for j, question in enumerate(criterion.questions or [])
                if f"q{i}_{j}" in raw
            }
            if flags:
                answers[criterion.id] = flags
            continue
        if f"q{i}" not in raw:
            continue
        answer = _choice_answer(raw[f"q{i}"], criterion)
        if answer is not None:
            answers[criterion.id] = answer
    return answers


class JevVerifier:
    """Второе мнение: один POST на диалог; не больше max_parallel запросов одновременно."""

    def __init__(self, api_key: str, http: httpx.AsyncClient, *, max_parallel: int = _MAX_PARALLEL) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._gate = asyncio.Semaphore(max_parallel)

    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict:
        body = {
            "model": _JEV_MODEL,
            "state": {"rules": rules, "dialog": dialog_text},
            "questions": _questions(criteria),
        }
        async with self._gate:
            response = await post_json(self._http, JEV_URL, body, self._headers)
        used = int((response.get("usage") or {}).get("input_tokens") or 0)
        return Verdict(
            answers=_answers(response.get("answers") or {}, criteria), cost=used * JEV_PRICE_IN / 1_000_000
        )
