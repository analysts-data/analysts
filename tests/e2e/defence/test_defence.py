"""Сценарий защиты: две версии выступления на общих шагах (design, решение 11)."""

import httpx
import pytest

from . import steps
from .steps import Defence, load_fixture

pytestmark = pytest.mark.e2e


def test_set_is_loaded_and_evaluated(defence_api: httpx.Client) -> None:
    state = defence_api.get("/api/state").raise_for_status().json()
    records = load_fixture("defence_set.json")["data"]["records"]
    assert sorted(x["id"] for x in state["dialogs"]) == sorted(r["conversation_id"] for r in records)
    criteria = {c["id"] for c in state["checklist"]["criteria"]}
    assert {x["id"]: set(x["res"]) for x in state["dialogs"]} == {x["id"]: criteria for x in state["dialogs"]}


@pytest.mark.xfail(reason="ждёт cqa-web-ui", strict=False)
def test_total_not_computable_shows_dash(defence: Defence) -> None:
    steps.no_total(defence)
