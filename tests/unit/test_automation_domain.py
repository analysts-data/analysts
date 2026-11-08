"""Автоматизация, чистое ядро: ошибки по полям, бюджет и тихие часы по часам-аргументу."""

from datetime import datetime

from cqa.domain.automation import AutomationSettings, allowance, check
from cqa.domain.review import ASTANA

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=ASTANA)


def _evaluate(**evaluate: object) -> AutomationSettings:
    return AutomationSettings.model_validate({"enabled": True, "evaluate": evaluate})


def test_invalid_field_gives_one_russian_error_at_its_location() -> None:
    settings, errors = check({"sync": {"every_min": 0}, "evaluate": {"sources": "some"}})
    assert settings is None
    assert [(e["loc"], e["msg"]) for e in errors] == [
        (["body", "sync", "every_min"], "Период — целое число минут, не меньше 1"),
        (["body", "evaluate", "sources"], 'Нужен список кодов источников или "all"'),
    ]


def test_allowance_stops_at_the_budget_and_in_quiet_hours_over_midnight() -> None:
    ev = _evaluate(daily_budget_usd=1.0, quiet_hours={"from": "22:00", "to": "08:00"}).evaluate
    assert allowance(ev, NOW, spent_today=1.0, evaluated_last_hour=0) == (0, "budget_reached")
    assert allowance(ev, NOW.replace(hour=23), spent_today=0, evaluated_last_hour=0) == (0, "quiet_hours")
    assert allowance(ev, NOW.replace(hour=23), spent_today=0, evaluated_last_hour=0, quiet=False)[1] is None
    assert allowance(ev, NOW, spent_today=0, evaluated_last_hour=55) == (5, None)
