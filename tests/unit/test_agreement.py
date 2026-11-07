"""Соглашение с эталоном: загрузка labels.jsonl и метрики прогона (чистые функции)."""

import json

from builders import v3_checklist


def gold_line(dlg: str, cid: str, ok, by: str = "team", note: str = "") -> str:
    return json.dumps({"dlg": dlg, "cid": cid, "ok": ok, "by": by, "note": note}, ensure_ascii=False)


# --- load_gold -----------------------------------------------------------------


def test_load_gold_accepts_contract_shapes() -> None:
    from cqa.domain.agreement import load_gold

    lines = [
        gold_line("p1-ru-009", "04", [5, 10]),
        gold_line("p1-ru-009", "02", None),
        gold_line("p1-ru-009", "08", [{"insult": False, "paid": False, "leak": True}], by="family"),
    ]
    gold = load_gold(lines, v3_checklist())

    assert [(g.dlg, g.cid, g.ok, g.by) for g in gold] == [
        ("p1-ru-009", "04", (5, 10), "team"),
        ("p1-ru-009", "02", None, "team"),
        ("p1-ru-009", "08", ({"insult": False, "paid": False, "leak": True},), "family"),
    ]


def test_load_gold_skips_empty_lines() -> None:
    from cqa.domain.agreement import load_gold

    gold = load_gold(["", gold_line("p1-ru-003", "01", ["yes"]), "  "], v3_checklist())

    assert len(gold) == 1


def test_load_gold_names_line_of_bad_json() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 2"):
        load_gold([gold_line("p1-ru-003", "01", ["yes"]), "{не json"], v3_checklist())


def test_load_gold_rejects_step_outside_steps() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError) as exc:
        load_gold([gold_line("p1-ru-003", "04", [12])], v3_checklist())

    message = str(exc.value)
    assert all(part in message for part in ("строка 1", "p1-ru-003", "04", "12"))


def test_load_gold_rejects_na_when_not_allowed() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*05.*na"):
        load_gold([gold_line("p1-ru-003", "05", ["na"])], v3_checklist())


def test_load_gold_rejects_answer_of_wrong_type() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*01"):
        load_gold([gold_line("p1-ru-003", "01", [5])], v3_checklist())
    with pytest.raises(ValueError, match="строка 1.*06"):
        load_gold([gold_line("p1-ru-003", "06", ["yes"])], v3_checklist())


def test_load_gold_rejects_foreign_flag_key() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*08.*bonus"):
        load_gold(
            [gold_line("p1-ru-003", "08", [{"insult": False, "paid": False, "leak": False, "bonus": True}])],
            v3_checklist(),
        )


def test_load_gold_rejects_incomplete_flag() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*08.*insult"):
        load_gold([gold_line("p1-ru-003", "08", [{"paid": False, "leak": False}])], v3_checklist())


def test_load_gold_rejects_duplicate_pair() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 2.*повтор.*p1-ru-003.*01"):
        load_gold(
            [gold_line("p1-ru-003", "01", ["yes"]), gold_line("p1-ru-003", "01", ["no"])],
            v3_checklist(),
        )


def test_load_gold_rejects_adjudicated_without_note() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*adjudicated.*note"):
        load_gold([gold_line("p1-ru-003", "01", ["no"], by="adjudicated")], v3_checklist())

    gold = load_gold(
        [gold_line("p1-ru-003", "01", ["no"], by="adjudicated", note="вопрос 3 организаторам")],
        v3_checklist(),
    )
    assert gold[0].by == "adjudicated"


def test_load_gold_rejects_unknown_criterion_and_bad_by() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*09"):
        load_gold([gold_line("p1-ru-003", "09", ["yes"])], v3_checklist())
    with pytest.raises(ValueError, match="строка 1.*by"):
        load_gold([gold_line("p1-ru-003", "01", ["yes"], by="model")], v3_checklist())


def test_load_gold_rejects_empty_ok_and_missing_fields() -> None:
    import pytest

    from cqa.domain.agreement import load_gold

    with pytest.raises(ValueError, match="строка 1.*ok"):
        load_gold([gold_line("p1-ru-003", "01", [])], v3_checklist())
    with pytest.raises(ValueError, match="строка 1"):
        load_gold([json.dumps({"dlg": "p1-ru-003", "ok": ["yes"], "by": "team", "note": ""})], v3_checklist())
