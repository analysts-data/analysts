"""eval/gold/labels.jsonl: настоящий эталон проходит проверку по чек-листу."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "eval" / "gold" / "labels.jsonl"
CHECKLIST_FIXTURE = ROOT / "tests" / "fixtures" / "checklist_v3.json"


def read_labels() -> list[dict]:
    assert LABELS.exists(), "eval/gold/labels.jsonl отсутствует"
    return [json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_eight_positive_subquestions_of_defect_families() -> None:
    """Ядро таблицы семеств: 3×leak, 4×paid, 1×insult — на месте."""
    expected = {
        ("p1-ru-009", "leak"),
        ("p1-kz-015", "leak"),
        ("p1-en-014", "leak"),
        ("p1-ru-022", "paid"),
        ("p1-ru-023", "paid"),
        ("p1-kz-013", "paid"),
        ("p1-en-013", "paid"),
        ("p1-ru-029", "insult"),
    }
    positives: set[tuple[str, str]] = set()
    for row in read_labels():
        for answer in row["ok"] or ():
            if isinstance(answer, dict):
                positives |= {(row["dlg"], key) for key, found in answer.items() if found}

    assert positives == expected


def test_labels_have_no_duplicate_pairs() -> None:
    rows = read_labels()
    pairs = [(row["dlg"], row["cid"]) for row in rows]

    assert len(pairs) == len(set(pairs))


def test_real_labels_pass_load_gold() -> None:
    if not CHECKLIST_FIXTURE.exists():
        pytest.skip("ждёт tests/fixtures/checklist_v3.json из bootstrap-harness")

    from cqa.domain.models import Checklist

    from cqa.domain.agreement import load_gold

    checklist = Checklist.model_validate_json(CHECKLIST_FIXTURE.read_text(encoding="utf-8"))
    gold = load_gold(LABELS.read_text(encoding="utf-8").splitlines(), checklist)

    assert len(gold) == len(read_labels())
    assert sum(1 for label in gold if label.ok is None) == 21  # спорные из разметки команды


def test_step_outside_scale_is_rejected_with_line_and_ids() -> None:
    from cqa.domain.agreement import load_gold

    lines = LABELS.read_text(encoding="utf-8").splitlines()
    first_04 = next(i for i, line in enumerate(lines) if json.loads(line)["cid"] == "04")
    lines.insert(
        first_04 + 1, json.dumps({"dlg": "p1-ru-003", "cid": "04", "ok": [12], "by": "team", "note": ""})
    )

    with pytest.raises(ValueError) as exc:
        load_gold(lines, _mini_checklist())

    message = str(exc.value)
    assert all(part in message for part in (str(first_04 + 2), "p1-ru-003", "04", "12"))


def _mini_checklist():
    from builders import v3_checklist

    return v3_checklist()
