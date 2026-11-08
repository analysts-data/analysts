"""Правила обработки: какой оценщик берёт диалог. Первое включённое правило, все условия которого
выполнены; последнее правило `default` — общий «Режим оценки», оно подходит любому диалогу."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

DEFAULT = "default"
_STRICT = ConfigDict(extra="forbid")  # опечатка в условии не должна молча подходить всем диалогам
_CH = {"chat": "чат", "call": "звонок"}


class Match(BaseModel):
    """Условия правила; не задано (null или пустой список) — условия нет."""

    model_config = _STRICT
    ch: Literal["chat", "call"] | None = None
    lang: list[str] | None = None
    source_id: list[str] | None = None
    product: list[str] | None = None
    min_lines: NonNegativeInt | None = None
    max_lines: NonNegativeInt | None = None
    has_audio: bool | None = None


class Use(BaseModel):
    """Действия правила поверх общего режима; поле не задано — как в общем режиме.

    `verifier: null`, заданный явно, — без второго мнения (отличается от «не задано»: `model_fields_set`).
    """

    model_config = _STRICT
    evaluator: Literal["llm", "jev"] | None = None
    llm_provider: str | None = None
    verifier: str | None = None
    anonymize: bool | None = None
    prosody: bool | None = None
    max_parallel: PositiveInt | None = None


class Rule(BaseModel):
    model_config = _STRICT
    id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    name: str = Field(min_length=1)
    enabled: bool = True
    why: str | None = None
    match: Match = Match()
    use: Use = Use()


@dataclass(frozen=True)
class Facts:
    """Что о диалоге видят условия; source_id и product — None, пока их нет у диалога."""

    ch: str
    lang: str
    source_id: str | None
    product: str | None
    lines: int  # реплики клиента, оператора и бота, без системных сообщений
    has_audio: bool


@dataclass(frozen=True)
class Condition:
    field: str
    ok: bool
    text: str  # «канал: чат — нужно звонок»


def _one_of(label: str, got: str | None, want: list[str]) -> tuple[bool, str]:
    ok = got is not None and got.casefold() in {w.casefold() for w in want}
    return ok, f"{label}: {got or 'не указан'} — нужно одно из {', '.join(want)}"


def conditions(rule: Rule, facts: Facts) -> list[Condition]:
    """Каждое заданное условие правила: выполнено ли и почему, в порядке полей `Match`."""
    m, out = rule.match, []
    if m.ch is not None:
        out.append(Condition("ch", facts.ch == m.ch, f"канал: {_CH[facts.ch]} — нужно {_CH[m.ch]}"))
    for name, label, got in (
        ("lang", "язык", facts.lang),
        ("source_id", "источник", facts.source_id),
        ("product", "продукт", facts.product),
    ):
        want = getattr(m, name)
        if want:
            out.append(Condition(name, *_one_of(label, got, want)))
    if m.min_lines is not None:
        text = f"реплик: {facts.lines} — нужно не меньше {m.min_lines}"
        out.append(Condition("min_lines", facts.lines >= m.min_lines, text))
    if m.max_lines is not None:
        text = f"реплик: {facts.lines} — нужно не больше {m.max_lines}"
        out.append(Condition("max_lines", facts.lines <= m.max_lines, text))
    if m.has_audio is not None:
        yes = {True: "есть", False: "нет"}
        text = f"запись разговора: {yes[facts.has_audio]} — нужно {yes[m.has_audio]}"
        out.append(Condition("has_audio", facts.has_audio == m.has_audio, text))
    return out


def matches(rule: Rule, facts: Facts) -> bool:
    return rule.enabled and all(c.ok for c in conditions(rule, facts))


def first_match(rules: list[Rule], facts: Facts) -> Rule:
    """Первое подходящее правило; список всегда кончается `default` без условий."""
    return next(r for r in rules if matches(r, facts))
