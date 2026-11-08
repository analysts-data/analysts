"""Data contract from design/contract.md and cross-track types from design/ports.md.

Optional fields are the ones the prototype mocks (design/cqa-v3) omit. Dump with
`model_dump(mode="json", exclude_unset=True)` to get exactly the contract shape back.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# "yes" | "no" | "na", a scale step, or a flag object {"insult": false, ...}
Answer = Literal["yes", "no", "na"] | int | dict[str, bool]

# `from` is a Python keyword: field `from_`, JSON key "from"
_BY_ALIAS = ConfigDict(validate_by_name=True, serialize_by_alias=True)


class Question(BaseModel):
    k: str
    label: str
    text: str | None = None


class JevQuestion(BaseModel):
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict[str, str] | list[str]
    min: int | None = None
    max: int | None = None


class Criterion(BaseModel):
    id: str
    sec: int
    name: str
    type: Literal["bool", "scale", "flag"]
    w: float
    na: bool = False
    naCond: str | None = None
    signal: Literal["resolution", "risk"] | None = None
    steps: list[int] | None = None
    stepText: dict[str, str] | None = None
    questions: list[Question] | None = None
    text: str
    call: str | None = None  # уточнение для звонка: модель получает его после text только на звонке
    channel: Literal["all", "chat", "call"] = "all"
    jev: JevQuestion | None = None

    def jev_descriptions(self) -> dict[str, str]:
        """Normalize source answer keys without changing the preserved Jev definition."""
        if self.jev is None:
            return {}
        criteria = self.jev.criteria
        items = criteria.items() if isinstance(criteria, dict) else ((key, key) for key in criteria)
        aliases = {"true": "yes", "false": "no", "not_applicable": "na"}
        return {aliases.get(key, key): text for key, text in items}

    def accepts(self, a: object) -> bool:
        """Whether `a` is a valid answer to this criterion (scale steps, N/A permission, flag keys)."""
        if a == "na":
            return self.na
        if self.type == "bool":
            return a in ("yes", "no")
        if self.type == "scale":
            return isinstance(a, int) and a in (self.steps or [])
        return (
            isinstance(a, dict)
            and set(a) == {q.k for q in self.questions or []}
            and all(isinstance(v, bool) for v in a.values())
        )


class Checklist(BaseModel):
    version: int
    rules: str
    sections: list[str]
    criteria: list[Criterion]


class Line(BaseModel):
    n: int
    t: float | str  # call: seconds; chat: "MM:SS" as in the source
    ts: str | None = None
    who: Literal["client", "operator", "bot", "system"]
    text: str
    s: float | None = None
    seg: Literal["pre", "conv", "internal", "after"] | None = None
    dup: bool | None = None


class Fold(BaseModel):
    model_config = _BY_ALIAS
    fold: Literal[True]
    from_: int = Field(validation_alias="from", serialization_alias="from")
    to: int
    t0: float | str
    t1: float | str
    label: str


class CriterionResult(BaseModel):
    a: Answer
    alt: Answer | None = None
    ev: list[int] = []
    seg: str | None = None
    why: str | None = None
    quote: str | None = None
    tag: str | None = None
    better: str | None = None
    evFail: bool = False
    model: str | None = None
    calls: int = 0
    cost: float = 0.0
    ms: int = 0


class Cost(BaseModel):  # Dialog.cost
    calls: int
    verifier_calls: int
    usd: float
    ms: int


class Dialog(BaseModel):
    id: str
    title: str | None = None
    ch: Literal["chat", "call"]
    lang: str
    dur: float | None = None
    at: str
    lines: list[Line | Fold] | None
    res: dict[str, CriterionResult] = {}
    reviewed: bool = False
    cost: Cost | None = None


class Appeal(BaseModel):
    model_config = _BY_ALIAS
    id: str
    kind: Literal["appeal", "review"]
    dlg: str
    cid: str
    from_: Answer = Field(validation_alias="from", serialization_alias="from")
    ask: Answer | None = None
    to: Answer | None = None
    ev: list[int] = []
    by: str
    at: str
    status: Literal["pending", "confirmed", "changed", "closed"]
    comment: str | None = None  # null у kind "review"
    reviewer: str | None = None
    reason: str | None = None
    decidedAt: str | None = None


class Mode(BaseModel):  # mode in GET /api/state
    where: Literal["kz", "local", "external"]
    anonymized: bool
    model: str
    verifier: str | None  # "jev", "self" (contract.md, never set) or a provider id


@dataclass(frozen=True)
class IngestResult:
    dialogs: list[Dialog]  # one per id, source order, without res and reviewed
    audio: dict[str, str]  # call id -> audio_url; goes to dialogs.audio_url, never into Dialog
    skipped: int  # broken records, == len(errors)
    errors: list[str]  # "<conversation_id>: <reason>"


@dataclass(frozen=True)
class Evaluation:
    cid: str
    result: CriterionResult


@dataclass(frozen=True)
class DialogEvaluation:
    results: list[Evaluation]  # one per answered criterion, in the order of the criteria argument
    verifier_calls: int  # second-opinion requests in this call (0 or 1)
    verifier_usd: float  # their price; not included in CriterionResult.cost
