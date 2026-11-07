"""scripts/demo.py check на сервере сценария защиты (release-and-runbook, «Проверка перед демонстрацией»)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from cqa.settings import Settings

from .steps import FIXTURES, load_fixture

pytestmark = pytest.mark.e2e
DRAFT = FIXTURES / "replacement_criterion.json"


def demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "demo", Path(__file__).resolve().parents[3] / "scripts" / "demo.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(api: httpx.Client, call: str | None = None) -> list[tuple[bool, str]]:
    d, s = demo(), Settings()
    picked = d.pick(api.get("/api/state").raise_for_status().json(), dev_ids=set())
    # DEV в наборе защиты нет: запасной диалог DEV (пример слайда 10) проверяет прогон на DEV
    own = {step: p for step, p in picked.items() if not p["fallback"]}
    return d.check(api, own, ["1"], call, s.llm_model, s.data_where, DRAFT)


def test_everything_ready(defence_api: httpx.Client) -> None:
    items = run_check(defence_api)
    assert all(ok for ok, _ in items), items


def test_new_version_leaves_picked_dialog_waiting(defence_api: httpx.Client) -> None:
    state = defence_api.get("/api/state").raise_for_status().json()
    draft = state["checklist"]
    replacement = load_fixture("replacement_criterion.json")
    draft["criteria"] = [replacement if c["id"] == replacement["id"] else c for c in draft["criteria"]]
    defence_api.put("/api/checklist", json=draft).raise_for_status()
    failed = [text for ok, text in run_check(defence_api) if not ok]
    assert failed and all(f"по критериям {replacement['id']}" in t for t in failed), failed


def test_call_without_recording_fails_without_printing_a_link(defence_api: httpx.Client) -> None:
    items = run_check(defence_api, call="call-024")
    assert (False, "запись call-024 недоступна") in items
    assert not any("http" in text for _, text in items)
