"""Jev: один запрос на диалог, choice на критерий, noul на подвопрос флага; второе мнение и «только Jev».

Формат API v1 (docs.typesafe.ai/api): вопрос — instructions и criteria; ответ choice —
{"choice": ключ criteria, ...}, ответ noul — {"noul": вероятность 0..1}.
"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from cqa.adapters.llm import post_json
from cqa.domain.models import Criterion
from cqa.services.evaluation import Verdict
from cqa.services.products import Pick

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
# Цена Jev, USD за 1 млн входных токенов; выход бесплатный (design/ports.md)
JEV_PRICE_IN = 0.042
_MAX_PARALLEL = 8
_INSTRUCTION = (
    "Оцени по dialog только реплики оператора; реплики с пометкой «не оценивается» — контекст; "
    "учитывай rules."
)


_PICK = (
    "Определи тему обращения клиента по dialog: тему задаёт вопрос клиента, а не ответ оператора. "
    "Если подходящей темы нет, выбери самую общую."
)


def _text(body: str) -> str:
    return f"{_INSTRUCTION}\n\n{body}"


def _choice_criteria(criterion: Criterion) -> dict[str, str | None]:
    """Ключ — ответ той же формы, что a; описание null — модель видит только ключ."""
    if criterion.type == "scale":
        options: dict[str, str | None] = {
            str(s): (criterion.stepText or {}).get(str(s)) for s in criterion.steps or []
        }
    else:
        options = {"yes": "Да", "no": "Нет"}
    if criterion.na:
        options["na"] = criterion.naCond or "Неприменимо"
    descriptions = criterion.jev_descriptions()
    return {key: descriptions.get(key, text) for key, text in options.items()}


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
                questions[f"q{i}_{j}"] = {
                    "type": "noul",
                    "instructions": _text(question.text or question.label),
                }
            continue
        questions[f"q{i}"] = {
            "type": "choice",
            "instructions": _text(criterion.text),
            "criteria": _choice_criteria(criterion),
        }
    return questions


def _number(value: Any) -> float | None:
    """Число из ответа v1, в том числе строкой; чужое значение — None."""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    return float(value) if isinstance(value, int | float) else None


def _found(value: Any) -> bool:
    """noul: доля 0..1, порог 0,5 (замер: 8 из 8 без ложных флагов); чужое значение — не найдено."""
    p = _number(value)
    return p is not None and p >= 0.5


def _field(raw: dict[str, Any], key: str, field: str) -> Any:
    """Значение ответа v1 по ключу вопроса; нет ответа или чужая форма — None."""
    answer = raw.get(key)
    return answer.get(field) if isinstance(answer, dict) else None


def _answers(raw: dict[str, Any], criteria: Sequence[Criterion]) -> dict[str, str | int | dict[str, bool]]:
    """Ключи ответа q{i} и q{i}_{j} обратно в id критерия; нет ключа — нет ответа."""
    answers: dict[str, str | int | dict[str, bool]] = {}
    for i, criterion in enumerate(criteria):
        if criterion.type == "flag":
            flags = {
                question.k: _found(_field(raw, f"q{i}_{j}", "noul"))
                for j, question in enumerate(criterion.questions or [])
                if f"q{i}_{j}" in raw
            }
            if flags:
                answers[criterion.id] = flags
            continue
        if f"q{i}" not in raw:
            continue
        answer = _choice_answer(_field(raw, f"q{i}", "choice"), criterion)
        if answer is not None:
            answers[criterion.id] = answer
    return answers


def _sure(answer: Any) -> float | None:
    """Вероятность ответа v1: choice — confidence или вероятность выбранного ключа, noul — max(p, 1 − p)."""
    if not isinstance(answer, dict):
        return None
    if "noul" in answer:
        p = _number(answer["noul"])
        return None if p is None else max(p, 1 - p)
    p = _number(answer.get("confidence"))
    if p is None and isinstance(answer.get("probabilities"), dict):
        p = _number(answer["probabilities"].get(str(answer.get("choice"))))
    return p


def _confidence(raw: dict[str, Any], criteria: Sequence[Criterion]) -> dict[str, float]:
    """id критерия → вероятность ответа; у флага — наименьшая по подвопросам с ответом."""
    out: dict[str, float] = {}
    for i, criterion in enumerate(criteria):
        keys = (
            [f"q{i}_{j}" for j in range(len(criterion.questions or []))]
            if criterion.type == "flag"
            else [f"q{i}"]
        )
        found = [p for k in keys if (p := _sure(raw.get(k))) is not None]
        if found:
            out[criterion.id] = min(found)
    return out


class JevVerifier:
    """Один POST на диалог: второе мнение или все ответы «только Jev»; не больше max_parallel сразу."""

    def __init__(self, api_key: str, http: httpx.AsyncClient, *, max_parallel: int = _MAX_PARALLEL) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._gate = asyncio.Semaphore(max_parallel)

    async def verify(self, dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict:
        body = {
            "model": JEV_MODEL,
            "state": {"rules": rules, "dialog": dialog_text},
            "questions": _questions(criteria),
        }
        async with self._gate:
            response = await post_json(self._http, JEV_URL, body, self._headers)
        used = int((response.get("usage") or {}).get("input_tokens") or 0)
        raw = response.get("answers") or {}
        return Verdict(
            answers=_answers(raw, criteria),
            cost=used * JEV_PRICE_IN / 1_000_000,
            confidence=_confidence(raw, criteria),
        )

    async def pick(self, dialog_text: str, options: Mapping[str, str]) -> Pick:
        """Тема обращения: один вопрос choice по справочнику тем, вероятность каждой темы из ответа."""
        body = {
            "model": JEV_MODEL,
            "state": {"dialog": dialog_text},
            "questions": {"q0": {"type": "choice", "instructions": _PICK, "criteria": dict(options)}},
        }
        async with self._gate:
            response = await post_json(self._http, JEV_URL, body, self._headers)
        used = int((response.get("usage") or {}).get("input_tokens") or 0)
        answer = (response.get("answers") or {}).get("q0")
        answer = answer if isinstance(answer, dict) else {}
        raw = answer.get("probabilities")
        probs = (
            {str(k): p for k, v in raw.items() if (p := _number(v)) is not None}
            if isinstance(raw, dict)
            else {}
        )
        choice = answer.get("choice")
        return Pick(
            choice=None if choice is None else str(choice),
            probs=probs,
            p=_sure(answer),
            cost=used * JEV_PRICE_IN / 1_000_000,
        )
