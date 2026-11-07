"""Сценарий защиты: две версии выступления на общих шагах (design, решение 11)."""

import httpx
import pytest

from . import steps
from .steps import Defence, load_fixture

pytestmark = pytest.mark.e2e

# шаг и окно выступления в секундах, таблица «Защита» docs/plan.md
VERSION_4M30 = (
    (steps.queue, 60),
    (steps.card, 60),
    (steps.na_and_call, 60),
    (steps.appeal, 60),
    (steps.replace, 30),
)
VERSION_3M00 = ((steps.card, 45), (steps.na_and_call, 45), (steps.appeal, 60), (steps.replace, 30))


def test_versions_fill_270_and_180_seconds() -> None:
    assert sum(window for _, window in VERSION_4M30) == 270
    assert sum(window for _, window in VERSION_3M00) == 180


def test_set_is_loaded_and_evaluated(defence_api: httpx.Client) -> None:
    state = defence_api.get("/api/state").raise_for_status().json()
    records = load_fixture("defence_set.json")["data"]["records"]
    assert sorted(x["id"] for x in state["dialogs"]) == sorted(r["conversation_id"] for r in records)
    criteria = {c["id"] for c in state["checklist"]["criteria"]}
    assert {x["id"]: set(x["res"]) for x in state["dialogs"]} == {x["id"]: criteria for x in state["dialogs"]}


def test_defence_4m30(defence: Defence) -> None:
    steps.mode_and_roles(defence)
    for step, _ in VERSION_4M30:
        step(defence)


def test_defence_3m00(defence: Defence) -> None:
    steps.mode_and_roles(defence)
    for step, _ in VERSION_3M00:
        step(defence)


def test_total_not_computable_shows_dash(defence: Defence) -> None:
    steps.no_total(defence)
