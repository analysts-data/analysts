"""Файл результатов «JSON 1.0» для организаторов (eval-and-delivery, группа 9).

Источник формата: context/CQA_Student_Guide_Appendix_Results.pdf, стр. 2–3.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from cqa.domain.models import Appeal, Checklist, Dialog
from cqa.domain.results import check_results, to_results
from fakes import prototype_checklist, prototype_dialogs

ROOT = Path(__file__).resolve().parents[2]
CODES: dict[str, str] = json.loads((ROOT / "results" / "criteria_map.json").read_text(encoding="utf-8"))
MODEL = {"mode": "external_api", "name": "qwen3-6"}

# стр. 3: код → (тип ответа у нас, допустимые числа, разрешён null)
PDF_TABLE = {
    "contact": ("bool", None, False),
    "discovery": ("bool", None, True),
    "identification": ("bool", None, True),
    "consultation": ("scale", [0, 5, 10, 15, 20], True),
    "empathy": ("bool", None, False),
    "dialogue": ("scale", [0, 4, 7, 10], False),
    "closure": ("bool", None, True),
    "critical": ("flag", None, False),
}


def proto(dialog_id: str) -> Dialog:
    return next(d for d in prototype_dialogs() if d.id == dialog_id)


def export(
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal] = (),
    ids: Sequence[str] | None = None,
    checklist: Checklist | None = None,
) -> dict[str, Any]:
    return to_results(
        [d.id for d in dialogs] if ids is None else ids,
        {d.id: d for d in dialogs},
        checklist or prototype_checklist(),
        appeals,
        CODES,
        team="analysts",
        model=MODEL,
    )


def record(dialog: Dialog, appeals: Sequence[Appeal] = ()) -> dict[str, Any]:
    return export([dialog], appeals)["results"][0]


def by_code(rec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["criterion_id"]: c for c in rec["criteria"]}


def decision(to: object, status: str = "changed", reason: str = "Срок назван полностью") -> Appeal:
    return Appeal.model_validate(
        {"id": "a1", "kind": "appeal", "dlg": "p1-ru-003", "cid": "04", "from": 5, "ask": 15, "to": to,
         "by": "Оператор", "at": "08.11 11:10", "status": status, "reason": reason}
    )  # fmt: skip


def test_criteria_map_matches_organisers_table_and_checklist() -> None:
    by_id = {c.id: c for c in prototype_checklist().criteria}
    assert list(CODES.values()) == list(PDF_TABLE)
    for cid, code in CODES.items():
        c = by_id[cid]
        assert (c.type, sorted(c.steps) if c.steps else None, c.na) == PDF_TABLE[code], code


def test_header_follows_json_1_0() -> None:
    assert export([]) == {"schema_version": "1.0", "team_name": "analysts", "model": MODEL, "results": []}


def test_answers_become_organisers_values_in_map_order() -> None:
    rec = record(proto("call-024"))

    assert (rec["conversation_id"], rec["status"]) == ("call-024", "ok")
    assert [(c["criterion_id"], c["value"]) for c in rec["criteria"]] == [
        ("contact", True),
        ("discovery", None),
        ("identification", True),
        ("consultation", 15),
        ("empathy", True),
        ("dialogue", 7),
        ("closure", False),
        ("critical", False),
    ]


def test_rationale_is_why_and_evidence_turns_are_source_line_numbers() -> None:
    dialog = proto("call-024")
    rows = by_code(record(dialog))

    assert rows["consultation"]["rationale"] == dialog.res["04"].why
    assert rows["consultation"]["evidence_turns"] == [9, 10]
    assert rows["critical"]["evidence_turns"] == []


def test_final_score_is_shared_formula_and_critical_flag_is_separate() -> None:
    assert record(proto("call-024"))["score"] == {"final_score": 82.94, "critical_flag": False}


def test_na_weight_is_redistributed_to_applicable_criteria() -> None:
    assert record(proto("p1-ru-025"))["score"]["final_score"] == 100.0


def test_critical_flag_is_true_when_any_violation_found_and_score_is_not_zeroed() -> None:
    rec = record(proto("p1-ru-022"))

    assert by_code(rec)["critical"]["value"] is True
    assert rec["score"]["critical_flag"] is True
    assert rec["score"]["final_score"] > 0


def test_latest_decision_overrides_model_answer_rationale_and_score() -> None:
    dialog = proto("p1-ru-003")

    before = record(dialog)
    after = record(dialog, [decision(15)])

    assert by_code(before)["consultation"]["value"] == 5
    assert by_code(after)["consultation"]["value"] == 15
    assert by_code(after)["consultation"]["rationale"] == "Срок назван полностью"
    assert (before["score"]["final_score"], after["score"]["final_score"]) == (41.0, 51.0)


def test_pending_appeal_does_not_change_the_answer() -> None:
    rec = record(proto("p1-ru-003"), [decision(None, status="pending", reason="")])

    assert by_code(rec)["consultation"]["value"] == 5


def test_dialog_missing_a_mapped_criterion_is_error_not_zero() -> None:
    dialog = proto("p1-ru-003")
    dialog = dialog.model_copy(update={"res": {k: v for k, v in dialog.res.items() if k != "04"}})

    rec = record(dialog)

    assert {k: v for k, v in rec.items() if k != "error"} == {
        "conversation_id": "p1-ru-003",
        "status": "error",
        "criteria": [],
        "score": None,
    }
    assert "04" in rec["error"]


def test_answer_the_criterion_does_not_accept_is_error() -> None:
    dialog = proto("p1-ru-003")
    bad = dialog.res["01"].model_copy(update={"a": "na"})  # N/A там, где чек-лист его не разрешает
    rec = record(dialog.model_copy(update={"res": {**dialog.res, "01": bad}}))

    assert rec["status"] == "error"
    assert "01" in rec["error"]


def test_dialog_absent_from_base_is_kept_as_error() -> None:
    [rec] = export([], ids=["ghost-1"])["results"]

    assert (rec["conversation_id"], rec["status"], rec["criteria"], rec["score"]) == (
        "ghost-1",
        "error",
        [],
        None,
    )
    assert rec["error"]


def test_records_follow_source_order() -> None:
    dialogs = prototype_dialogs()
    ids = [d.id for d in reversed(dialogs)]

    assert [r["conversation_id"] for r in export(dialogs, ids=ids)["results"]] == ids


def test_map_criterion_missing_from_checklist_raises() -> None:
    checklist = prototype_checklist()
    checklist = checklist.model_copy(update={"criteria": checklist.criteria[:-1]})

    with pytest.raises(ValueError, match="08"):
        export([proto("call-024")], checklist=checklist)


def test_check_results_accepts_valid_export() -> None:
    doc = export(prototype_dialogs(), ids=[*(d.id for d in prototype_dialogs()), "ghost-1"])

    assert check_results(doc, CODES.values()) == []
    assert check_results(doc, CODES.values(), expected=11) == []


def test_check_results_reports_duplicate_ids_missing_codes_and_wrong_count() -> None:
    doc = export([proto("call-024"), proto("p1-ru-003")])
    doc["results"][1]["conversation_id"] = "call-024"
    doc["results"][0]["criteria"].pop()

    problems = "\n".join(check_results(doc, CODES.values(), expected=10))

    assert "call-024" in problems and "повтор" in problems
    assert "critical" in problems
    assert "10" in problems
