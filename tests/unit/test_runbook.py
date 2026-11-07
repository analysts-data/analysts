"""docs/runbook.md: регламент контрольного часа и защиты (release-and-runbook)."""

from pathlib import Path

import pytest

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbook.md"

REQUIRED = [
    "10:00",
    "10:30",
    "11:00",
    "11:45",
    "12:00",
    "group_id",
    "git tag -a v1.0",
    "make backup",
    "--runxfail",
    "scripts/demo.py pick",
    "scripts/demo.py check",
    "p4-ru-002",
    "120 запросов в минуту",
    "Итог не рассчитывается",
    "за 15 минут",
    "только блокирующие",
]


@pytest.mark.parametrize("needle", REQUIRED)
def test_runbook_names_every_step(needle: str) -> None:
    assert needle in RUNBOOK.read_text(encoding="utf-8"), needle
