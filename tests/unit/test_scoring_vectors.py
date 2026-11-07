"""Общие векторы итога: форма и якорные значения.

Файл `tests/fixtures/scoring_vectors.json` читают и pytest, и `node --test`
(tests/node/scoring_vectors.test.js); число векторов в обоих раннерах одинаковое.
`checklist` в векторе — `"prototype"` (ссылка на `checklist_v3.json`) или встроенный
чек-лист для векторов с нестандартными весами.
"""

import json
from pathlib import Path

from cqa.domain.models import Checklist
from cqa.domain.scoring import total

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXPECTED_VECTORS = 7


def load_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf8"))


def resolve_checklist(ref: object) -> Checklist:
    if isinstance(ref, str):
        return Checklist.model_validate(load_fixture("checklist_v3.json"))
    return Checklist.model_validate(ref)


def vectors() -> list[dict]:
    raw = load_fixture("scoring_vectors.json")
    assert isinstance(raw, list)
    return raw


def test_vectors_count_matches_node_runner() -> None:
    assert len(vectors()) == EXPECTED_VECTORS


def test_vectors_have_shared_shape_and_valid_answers() -> None:
    for vector in vectors():
        assert set(vector) == {"name", "checklist", "answers", "total"}, vector["name"]
        checklist = resolve_checklist(vector["checklist"])
        by_id = {c.id: c for c in checklist.criteria}
        for cid, answer in vector["answers"].items():
            assert cid in by_id, f"{vector['name']}: неизвестный критерий {cid}"
            assert by_id[cid].accepts(answer), f"{vector['name']}: {cid} не принимает {answer!r}"
        assert vector["total"] is None or isinstance(vector["total"], (int, float))


def test_vectors_keep_prototype_anchors() -> None:
    totals = {v["name"]: v["total"] for v in vectors()}

    assert totals["пример из чек-листа: 77,69"] == 77.69
    assert totals["звонок 024: 82,94"] == 82.94
    assert totals["нет применимых критериев: итог null"] is None
    # 100 × 7,7 / 16 = 48,125: половина вверх даёт 48,13, а не 48,12
    assert totals["шум двоичной записи: 48,125 → 48,13"] == 48.13


def test_python_total_matches_every_vector() -> None:
    for vector in vectors():
        checklist = resolve_checklist(vector["checklist"])
        assert total(checklist, vector["answers"]) == vector["total"], vector["name"]
