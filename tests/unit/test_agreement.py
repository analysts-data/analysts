"""Соглашение с эталоном: загрузка labels.jsonl и метрики прогона (чистые функции)."""

import json

from builders import dialog, result, v3_checklist


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


# --- score_run: совпадение -----------------------------------------------------------------


def test_score_run_counts_agreement_by_total_lang_and_cid() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines = [
        gold_line("p1-ru-006", "01", ["yes"]),
        gold_line("p1-ru-009", "01", ["yes"]),
        gold_line("p1-ru-022", "01", ["no"]),
        gold_line("p1-kz-003", "01", ["yes"]),
        gold_line("p1-kz-008", "01", ["no"]),
        gold_line("p1-ru-025", "04", [5, 10]),  # несколько допустимых ступеней
        gold_line("p1-kz-015", "08", [{"insult": False, "paid": False, "leak": True}]),
        gold_line("p1-ru-002", "03", None),  # спорное — вне счёта
        gold_line("p1-kz-013", "07", ["na"]),  # записи нет — несовпадение и missing
    ]
    gold = load_gold(lines, v3_checklist())
    results = {
        "p1-ru-006": {"01": result("yes")},
        "p1-ru-009": {"01": result("yes")},
        "p1-ru-022": {"01": result("yes")},  # несовпадение
        "p1-kz-003": {"01": result("yes")},
        "p1-kz-008": {"01": result("yes")},  # несовпадение
        "p1-ru-025": {"04": result(10)},  # ступень из списка допустимых
        "p1-kz-015": {
            "08": result({"insult": False, "paid": False, "leak": True})
        },  # флаг — равенство объекта
    }
    dialogs = {
        "p1-ru-006": dialog("p1-ru-006"),
        "p1-ru-009": dialog("p1-ru-009"),
        "p1-ru-022": dialog("p1-ru-022"),
        "p1-ru-025": dialog("p1-ru-025"),
        "p1-ru-002": dialog("p1-ru-002"),
        "p1-kz-003": dialog("p1-kz-003", lang="KZ"),
        "p1-kz-008": dialog("p1-kz-008", lang="KZ"),
        "p1-kz-013": dialog("p1-kz-013", lang="KZ"),
        "p1-kz-015": dialog("p1-kz-015", lang="KZ"),
    }

    metrics = score_run(gold, results, dialogs, v3_checklist())

    assert (metrics.agree_total.n, metrics.agree_total.ok) == (8, 5)
    assert metrics.agree_total.frac == 0.625
    assert (metrics.per_lang["RU"].n, metrics.per_lang["RU"].ok) == (4, 3)
    assert (metrics.per_lang["KZ"].n, metrics.per_lang["KZ"].ok) == (4, 2)
    assert (metrics.per_cid["01"].n, metrics.per_cid["01"].ok) == (5, 3)
    assert metrics.missing == 1


def test_score_run_ru_kz_gap_is_15_points() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    for i in range(20):
        ru, kz = f"p1-ru-1{i:02d}", f"p1-kz-1{i:02d}"
        lines += [gold_line(ru, "01", ["yes"]), gold_line(kz, "01", ["yes"])]
        results[ru] = {"01": result("yes")}
        results[kz] = {"01": result("yes" if i < 17 else "no")}
        dialogs[ru] = dialog(ru)
        dialogs[kz] = dialog(kz, lang="KZ")

    metrics = score_run(load_gold(lines, v3_checklist()), results, dialogs, v3_checklist())

    assert metrics.per_lang["RU"].frac == 1.0
    assert round(metrics.per_lang["KZ"].frac * 100) == 85
    assert round(metrics.kz_gap_pts, 1) == 15.0


def test_score_run_collects_disagreements() -> None:
    from cqa.domain.agreement import load_gold, score_run

    gold = load_gold(
        [gold_line("p1-ru-006", "04", [15, 20]), gold_line("p1-kz-013", "07", ["na"])],
        v3_checklist(),
    )
    results = {
        "p1-ru-006": {"04": result(10, why="Срок не назван", quote="передам вопрос")},
        "p1-kz-013": {},
    }
    dialogs = {"p1-ru-006": dialog("p1-ru-006"), "p1-kz-013": dialog("p1-kz-013", lang="KZ")}

    metrics = score_run(gold, results, dialogs, v3_checklist())

    assert [(d.dlg, d.cid, d.gold, d.got, d.why, d.quote) for d in metrics.disagreements] == [
        ("p1-ru-006", "04", [15, 20], 10, "Срок не назван", "передам вопрос"),
        ("p1-kz-013", "07", ["na"], None, None, None),
    ]


# --- score_run: грубые ошибки --------------------------------------------------------------


LEAK = {"insult": False, "paid": False, "leak": True}
CLEAN = {"insult": False, "paid": False, "leak": False}


def _flag_gold() -> tuple:
    """Восемь положительных подвопросов таблицы семейств + чистый диалог."""
    rows = [
        ("p1-ru-009", "RU", {"insult": False, "paid": False, "leak": True}),
        ("p1-kz-015", "KZ", {"insult": False, "paid": False, "leak": True}),
        ("p1-en-014", "EN", {"insult": False, "paid": False, "leak": True}),
        ("p1-ru-022", "RU", {"insult": False, "paid": True, "leak": False}),
        ("p1-ru-023", "RU", {"insult": False, "paid": True, "leak": False}),
        ("p1-kz-013", "KZ", {"insult": False, "paid": True, "leak": False}),
        ("p1-en-013", "EN", {"insult": False, "paid": True, "leak": False}),
        ("p1-ru-029", "RU", {"insult": True, "paid": False, "leak": False}),
        ("p1-ru-006", "RU", CLEAN),
    ]
    lines = [gold_line(dlg, "08", [answer]) for dlg, _lang, answer in rows]
    dialogs = {dlg: dialog(dlg, lang=lang) for dlg, lang, _ in rows}
    return rows, lines, dialogs


def test_gross_recall_by_subquestion_and_language() -> None:
    from cqa.domain.agreement import load_gold, score_run

    rows, lines, dialogs = _flag_gold()
    results: dict = {}
    for dlg, _lang, answer in rows:
        got = dict(CLEAN) if dlg == "p1-kz-015" else dict(answer)  # пропуск leak на казахском
        if dlg == "p1-ru-006":
            got = {"insult": True, "paid": False, "leak": False}  # ложный флаг
        results[dlg] = {"08": result(got)}

    metrics = score_run(load_gold(lines, v3_checklist()), results, dialogs, v3_checklist())
    gross = metrics.gross

    assert gross.recall["leak"] == 2 / 3
    assert gross.recall["paid"] == 1.0
    assert gross.recall["insult"] == 1.0
    assert gross.overall == 7 / 8
    assert gross.by_lang["KZ"] == 0.5
    assert gross.by_lang["RU"] == 1.0
    assert gross.by_lang["EN"] == 1.0
    assert gross.missed == [("p1-kz-015", "leak")]
    assert gross.false_flags == 1


def test_gross_without_positives_is_null() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines = [gold_line("p1-ru-006", "08", [CLEAN])]
    metrics = score_run(
        load_gold(lines, v3_checklist()),
        {"p1-ru-006": {"08": result(dict(CLEAN))}},
        {"p1-ru-006": dialog("p1-ru-006")},
        v3_checklist(),
    )

    assert metrics.gross.recall["leak"] is None
    assert metrics.gross.overall is None
    assert metrics.gross.missed == []
    assert metrics.gross.false_flags == 0


# --- score_run: N/A ------------------------------------------------------------------------


def test_na_precision_and_recall() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    for i in range(10):
        dlg = f"p1-ru-2{i:02d}"
        lines.append(gold_line(dlg, "02", ["na"]))  # 10 положительных na в эталоне
        results[dlg] = {"02": result("na" if i < 9 else "no")}  # 9 найдено, один пропуск
        dialogs[dlg] = dialog(dlg)
    lines.append(gold_line("p1-ru-299", "02", ["no"]))  # и один na там, где эталон no
    results["p1-ru-299"] = {"02": result("na")}
    dialogs["p1-ru-299"] = dialog("p1-ru-299")

    metrics = score_run(load_gold(lines, v3_checklist()), results, dialogs, v3_checklist())

    assert metrics.na.precision == 0.9
    assert metrics.na.recall == 0.9


def test_na_recall_below_eight_tenths_is_reported() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    for i in range(10):
        dlg = f"p1-kz-2{i:02d}"
        lines.append(gold_line(dlg, "03", ["na"]))
        results[dlg] = {"03": result("na" if i < 8 else "yes")}  # найдено 8 из 10
        dialogs[dlg] = dialog(dlg, lang="KZ")

    metrics = score_run(load_gold(lines, v3_checklist()), results, dialogs, v3_checklist())

    assert metrics.na.recall == 0.8


def test_na_on_disallowed_criterion_is_mismatch_but_not_in_na_stats() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines = [gold_line("p1-ru-006", "02", ["na"]), gold_line("p1-ru-007", "01", ["no"])]
    results = {
        "p1-ru-006": {"02": result("na")},
        "p1-ru-007": {"01": result("na")},  # na у критерия без na: false
    }
    dialogs = {"p1-ru-006": dialog("p1-ru-006"), "p1-ru-007": dialog("p1-ru-007")}

    metrics = score_run(load_gold(lines, v3_checklist()), results, dialogs, v3_checklist())

    assert metrics.na.precision == 1.0
    assert metrics.na.recall == 1.0
    assert (metrics.agree_total.n, metrics.agree_total.ok) == (2, 1)  # второй ответ — несовпадение


def test_na_metrics_are_null_on_empty_denominator() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines = [gold_line("p1-ru-006", "01", ["yes"])]
    metrics = score_run(
        load_gold(lines, v3_checklist()),
        {"p1-ru-006": {"01": result("yes")}},
        {"p1-ru-006": dialog("p1-ru-006")},
        v3_checklist(),
    )

    assert metrics.na.precision is None
    assert metrics.na.recall is None
