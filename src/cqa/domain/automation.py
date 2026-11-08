"""Автоматизация: настройки как данные и решения цикла. Чистые функции, часы — аргумент `now`.

Время дня (тихие часы, «сегодня» для бюджета) — по Алматы (`ASTANA`, UTC+5).
"""

import re
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

from cqa.domain.models import Dialog
from cqa.domain.review import ASTANA

State = Literal["off", "idle", "syncing", "evaluating", "paused", "budget_reached", "quiet_hours"]
Phase = Literal["syncing", "evaluating"]
Skip = Literal["budget_reached", "quiet_hours", "hour_limit"]
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class QuietHours(_Strict):
    from_: str = Field(alias="from")
    to: str

    @field_validator("from_", "to")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.fullmatch(v):
            raise ValueError("ЧЧ:ММ")
        return v


class Sync(_Strict):
    enabled: StrictBool = True
    every_min: int = Field(default=5, ge=1)
    sources: list[str] | Literal["all"] = "all"


class Evaluate(_Strict):
    enabled: StrictBool = True
    on_new_dialogs: StrictBool = True
    sources: list[str] | Literal["all"] = "all"
    ch: list[Literal["chat", "call"]] | Literal["all"] = "all"
    lang: list[str] | Literal["all"] = "all"
    batch_size: int = Field(default=20, ge=1, le=500)
    priority: Literal["low", "normal", "high"] = "normal"
    max_per_hour: int = Field(default=60, ge=1)
    daily_budget_usd: float = Field(default=1.0, gt=0)
    quiet_hours: QuietHours | None = None
    only_unscored: StrictBool = True


class After(_Strict):
    classify_products: StrictBool = False
    evaluate_alerts: StrictBool = True
    prosody_for_calls: StrictBool = False


class AutomationSettings(_Strict):
    enabled: StrictBool = False
    sync: Sync = Sync()
    evaluate: Evaluate = Evaluate()
    after: After = After()


BOOL = "Нужно true или false"
MESSAGES = {
    "every_min": "Период — целое число минут, не меньше 1",
    "sources": 'Нужен список кодов источников или "all"',
    "ch": 'Нужен список каналов "chat", "call" или "all"',
    "lang": 'Нужен список языков, например ["RU", "KZ"], или "all"',
    "batch_size": "Размер пачки — целое число от 1 до 500",
    "priority": 'Приоритет — "low", "normal" или "high"',
    "max_per_hour": "Лимит в час — целое число диалогов, не меньше 1",
    "daily_budget_usd": "Бюджет в день — число USD больше 0",
    "quiet_hours": 'Тихие часы — {"from": "22:00", "to": "08:00"} или null',
    "from": "Время в формате ЧЧ:ММ, например 22:00",
    "to": "Время в формате ЧЧ:ММ, например 08:00",
    "sync": "Нужен объект настроек синхронизации",
    "evaluate": "Нужен объект настроек оценки",
    "after": "Нужен объект шагов после оценки",
}


def _loc(loc: tuple[int | str, ...]) -> tuple[int | str, ...]:
    """Путь поля до метки варианта union (`list[str]`, `literal['all']`): ошибка union — одна, на поле."""
    for i, part in enumerate(loc):
        if isinstance(part, str) and not re.fullmatch(r"\w+", part):
            return loc[:i]
    return loc


def _msg(error: Mapping[str, Any], field: str) -> str:
    if error["type"] == "extra_forbidden":
        return "Неизвестное поле"
    return MESSAGES.get(field, BOOL if error["type"].startswith("bool") else "Неверное значение")


def check(raw: Any) -> tuple[AutomationSettings | None, list[dict[str, Any]]]:
    """Настройки или ошибки по полям `[{loc: ["body", ...], msg}]` по-русски, по одной на поле."""
    try:
        return AutomationSettings.model_validate(raw), []
    except ValidationError as exc:
        errors: dict[tuple[int | str, ...], dict[str, Any]] = {}
        for e in exc.errors():
            loc = _loc(e["loc"])
            field = next((p for p in reversed(loc) if isinstance(p, str)), "")
            errors.setdefault(loc, {"loc": ["body", *loc], "msg": _msg(e, field)})
        return None, list(errors.values())


def in_quiet_hours(quiet: QuietHours | None, now: datetime) -> bool:
    """[from, to) по Алматы; from > to — через полночь; from == to — тихих часов нет."""
    if quiet is None:
        return False
    t = now.astimezone(ASTANA).strftime("%H:%M")
    if quiet.from_ <= quiet.to:
        return quiet.from_ <= t < quiet.to
    return t >= quiet.from_ or t < quiet.to


def _chosen(pick: Sequence[str], value: str | None) -> bool:
    return pick == "all" or value in pick


def due_sources(
    pick: Sequence[str],
    known: Sequence[str],
    last: Mapping[str, datetime],
    every_min: int,
    now: datetime,
) -> list[str]:
    """Выбранные источники, которые ещё не синхронизировались или ждут дольше периода."""
    period = timedelta(minutes=every_min)
    return [s for s in known if _chosen(pick, s) and (s not in last or now - last[s] >= period)]


def allowance(
    ev: Evaluate, now: datetime, *, spent_today: float, evaluated_last_hour: int, quiet: bool = True
) -> tuple[int, Skip | None]:
    """Сколько диалогов можно отдать модели сейчас и почему нисколько. quiet=False — запуск вручную."""
    if spent_today >= ev.daily_budget_usd:
        return 0, "budget_reached"
    if quiet and in_quiet_hours(ev.quiet_hours, now):
        return 0, "quiet_hours"
    left = ev.max_per_hour - evaluated_last_hour
    if left <= 0:
        return 0, "hour_limit"
    return min(ev.batch_size, left), None


def totals(cycles: Sequence[Mapping[str, Any]], now: datetime, *, budget: float) -> dict[str, Any]:
    """Сегодня по Алматы: оценено диалогов и потрачено; `last_hour` — оценено за последние 60 минут."""
    day = now.astimezone(ASTANA).date()
    today = [c for c in cycles if datetime.fromisoformat(c["started"]).astimezone(ASTANA).date() == day]
    hour_ago = now - timedelta(hours=1)
    cost = round(sum(c["cost"] for c in today), 6)
    return {
        "dialogs_evaluated": sum(c["evaluated"] for c in today),
        "cost_usd": cost,
        "budget_left": round(max(budget - cost, 0.0), 6),
        "last_hour": sum(
            c["evaluated"]
            for c in cycles
            if c["finished"] and datetime.fromisoformat(c["finished"]) > hour_ago
        ),
    }


def next_run_at(
    s: AutomationSettings, *, paused: bool, last_started: datetime | None, now: datetime
) -> datetime | None:
    """Следующий плановый цикл: сразу, если циклов не было; None — выключено или пауза."""
    if not s.enabled or paused:
        return None
    return now if last_started is None else last_started + timedelta(minutes=s.sync.every_min)


def state(
    s: AutomationSettings, now: datetime, *, phase: Phase | None, paused: bool, spent_today: float
) -> State:
    if not s.enabled:
        return "off"
    if phase is not None:
        return phase
    if paused:
        return "paused"
    if s.evaluate.enabled and spent_today >= s.evaluate.daily_budget_usd:
        return "budget_reached"
    if s.evaluate.enabled and in_quiet_hours(s.evaluate.quiet_hours, now):
        return "quiet_hours"
    return "idle"


def candidates(
    ev: Evaluate,
    dialogs: Sequence[Dialog],
    *,
    todo: Collection[str],
    scored: Collection[str],
    source: Mapping[str, str],
    blocked: Collection[str],
) -> list[str]:
    """Очередь оценки, новые первыми: есть пары без ответа (`todo`), без оценок вовсе при `only_unscored`,
    не `block` по достаточности, под фильтры источника, канала и языка."""
    return [
        d.id
        for d in reversed(dialogs)
        if d.id in todo
        and not (ev.only_unscored and d.id in scored)
        and d.id not in blocked
        and _chosen(ev.sources, source.get(d.id))
        and _chosen(ev.ch, d.ch)
        and _chosen(ev.lang, d.lang)
    ]
