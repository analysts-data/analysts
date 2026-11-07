"""scripts/demo.py: подбор диалогов для защиты и подсказка без кассет (release-and-runbook)."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo = load()

CHECKLIST = {
    "criteria": [
        {"id": "01", "type": "bool", "w": 10, "na": False},
        {"id": "02", "type": "bool", "w": 15, "na": True, "naCond": "Данных хватало с начала."},
        {"id": "04", "type": "scale", "w": 20, "steps": [20, 15, 10, 5, 0], "na": True},
        {"id": "08", "type": "flag", "w": 0, "questions": [{"k": "insult"}, {"k": "paid"}]},
    ]
}
CLEAN = {
    "01": {"a": "yes", "ev": [1]},
    "02": {"a": "yes"},
    "04": {"a": 20, "ev": [1]},
    "08": {"a": {"insult": False}},
}


def dialog(id_: str, lines: int = 5, ch: str = "chat", **res: dict[str, Any]) -> dict[str, Any]:
    body = [{"n": n, "t": n, "who": "operator", "text": "x", "s": float(n)} for n in range(1, lines + 1)]
    return {"id": id_, "ch": ch, "lines": body, "res": {**CLEAN, **res}}


def state(*dialogs: dict[str, Any], appeals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"checklist": CHECKLIST, "dialogs": list(dialogs), "appeals": appeals or []}


def test_control_set_without_calls_falls_back_to_dev_call_with_a_phrase() -> None:
    picked = demo.pick(state(dialog("c1"), dialog("p4-ru-002", ch="call")), dev_ids={"p4-ru-002"})
    assert picked["call"]["id"] == "p4-ru-002"
    assert picked["call"]["fallback"] is True
    assert picked["call"]["say"] == "В контрольном наборе звонков нет, показываем звонок из DEV"


def test_scale_on_max_is_not_an_appeal_candidate() -> None:
    a = dialog("a", **{"04": {"a": 20, "ev": [2]}})
    b = dialog("b", **{"04": {"a": 15, "ev": [3]}})
    assert demo.pick(state(a, b), dev_ids=set())["appeal"] == {"id": "b", "cid": "04", "fallback": False}


def test_pair_with_an_appeal_is_skipped() -> None:
    b = dialog("b", **{"04": {"a": 15, "ev": [3]}})
    taken = [{"dlg": "b", "cid": "04", "kind": "appeal", "status": "pending"}]
    assert demo.pick(state(b, appeals=taken), dev_ids=set())["appeal"]["fallback"] is True


def test_shorter_dialog_wins_for_gross_error() -> None:
    flag = {"08": {"a": {"insult": True}, "ev": [2]}}
    picked = demo.pick(state(dialog("long", 40, **flag), dialog("short", 12, **flag)), dev_ids=set())
    assert picked["gross"] == {"id": "short", "cid": "08", "fallback": False}


def test_na_needs_condition_and_an_applicable_weighted_criterion() -> None:
    picked = demo.pick(state(dialog("n", **{"02": {"a": "na"}})), dev_ids=set())
    assert picked["na"] == {"id": "n", "cid": "02", "fallback": False}


def test_call_needs_start_seconds_on_evidence_lines() -> None:
    call = dialog("call", ch="call")
    call["lines"][0]["s"] = None
    assert demo.pick(state(call), dev_ids=set())["call"]["fallback"] is True
    assert demo.pick(state(dialog("call2", ch="call")), dev_ids=set())["call"]["id"] == "call2"


def test_dev_dialogs_are_not_control_candidates() -> None:
    flag = {"08": {"a": {"insult": True}, "ev": [2]}}
    picked = demo.pick(state(dialog("p1-ru-022", 3, **flag)), dev_ids={"p1-ru-022"})
    assert picked["gross"]["id"] == "p1-ru-022"
    assert picked["gross"]["fallback"] is True
    assert "DEV" in picked["gross"]["say"]


def test_serve_without_cassettes_names_make_record(tmp_path: Path) -> None:
    message = demo.missing_cassettes(tmp_path)
    assert message and "make record" in message
    (tmp_path / "abc.json").write_text("{}")
    assert demo.missing_cassettes(tmp_path) is None
