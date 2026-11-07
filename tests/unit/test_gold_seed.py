"""scripts/gold_seed.py: перевод разметки команды в строки эталона.

Токены: `y`/`n`/`a`, ступени через `|`, `?` — спорно (`ok: null`), `-` — не размечено.
Для флага `n` — все подвопросы false, `y:<k>[,<k>]` — названные true; ключи из чек-листа.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gold_seed.py"

# Данные того же состава, что tests/fixtures/checklist_v3.json: восемь критериев,
# флаг с подвопросами insult/paid/leak, две шкалы.
CRITERIA = [
    {"id": "01", "type": "bool", "na": False},
    {"id": "02", "type": "bool", "na": True},
    {"id": "03", "type": "bool", "na": True},
    {"id": "04", "type": "scale", "na": True, "steps": [20, 15, 10, 5, 0]},
    {"id": "05", "type": "bool", "na": False},
    {"id": "06", "type": "scale", "na": False, "steps": [10, 7, 4, 0]},
    {"id": "07", "type": "bool", "na": True},
    {
        "id": "08",
        "type": "flag",
        "na": False,
        "questions": [{"k": "insult"}, {"k": "paid"}, {"k": "leak"}],
    },
]


def load_module() -> SimpleNamespace:
    spec = importlib.util.spec_from_file_location("gold_seed", SCRIPT)
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module  # type: ignore[return-value]


@pytest.fixture(scope="module")
def gold_seed() -> SimpleNamespace:
    return load_module()


def test_team_line_with_leak(gold_seed) -> None:
    rows = gold_seed.seed_rows("p1-ru-009 y ? n 5|10 ? 4|7 y y:leak", CRITERIA)

    assert [(r["cid"], r["ok"]) for r in rows] == [
        ("01", ["yes"]),
        ("02", None),
        ("03", ["no"]),
        ("04", [5, 10]),
        ("05", None),
        ("06", [4, 7]),
        ("07", ["yes"]),
        ("08", [{"insult": False, "paid": False, "leak": True}]),
    ]
    assert all(r["dlg"] == "p1-ru-009" and r["by"] == "team" and r["note"] == "" for r in rows)


def test_dash_gives_no_row_and_na_is_allowed(gold_seed) -> None:
    rows = gold_seed.seed_rows("p1-ru-012 - - - - - - a -", CRITERIA)

    assert rows == [{"dlg": "p1-ru-012", "cid": "07", "ok": ["na"], "by": "team", "note": ""}]


def test_clean_flag_lists_all_subquestions_false(gold_seed) -> None:
    rows = gold_seed.seed_rows("p1-ru-025 y ? a a y 10 a n", CRITERIA)

    flag = next(r for r in rows if r["cid"] == "08")
    assert flag["ok"] == [{"insult": False, "paid": False, "leak": False}]


def test_several_named_flag_subquestions(gold_seed) -> None:
    rows = gold_seed.seed_rows("p1-ru-001 y ? a a y 10 a y:insult,paid", CRITERIA)

    flag = next(r for r in rows if r["cid"] == "08")
    assert flag["ok"] == [{"insult": True, "paid": True, "leak": False}]


def test_by_token_family(gold_seed) -> None:
    rows = gold_seed.seed_rows("p1-ru-010 - - - 15|20 - - - - family", CRITERIA)

    assert rows == [{"dlg": "p1-ru-010", "cid": "04", "ok": [15, 20], "by": "family", "note": ""}]


def test_flag_without_subquestion_is_rejected(gold_seed) -> None:
    with pytest.raises(ValueError, match="08.*подвопрос"):
        gold_seed.seed_rows("p1-ru-009 y ? n 5|10 ? 4|7 y y", CRITERIA)


def test_unknown_flag_subquestion_is_rejected(gold_seed) -> None:
    with pytest.raises(ValueError, match="unknown"):
        gold_seed.seed_rows("p1-ru-009 y ? n 5|10 ? 4|7 y y:unknown", CRITERIA)


def test_wrong_token_count_is_rejected(gold_seed) -> None:
    with pytest.raises(ValueError, match="токенов"):
        gold_seed.seed_rows("p1-ru-009 y ? n 5|10 ? 4|7", CRITERIA)


def test_unknown_token_is_rejected(gold_seed) -> None:
    with pytest.raises(ValueError, match="02.*x"):
        gold_seed.seed_rows("p1-ru-009 y x n 5|10 ? 4|7 y n", CRITERIA)


def test_main_prints_jsonl(tmp_path, capsys, gold_seed) -> None:
    seed = tmp_path / "seed.txt"
    checklist = tmp_path / "checklist.json"
    seed.write_text("p1-ru-012 - - - - - - a -\n", encoding="utf-8")
    checklist.write_text(json.dumps({"criteria": CRITERIA}), encoding="utf-8")

    code = gold_seed.main(["--seed", str(seed), "--checklist", str(checklist)])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "dlg": "p1-ru-012",
        "cid": "07",
        "ok": ["na"],
        "by": "team",
        "note": "",
    }
