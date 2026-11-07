"""Соглашение с эталоном: загрузка labels.jsonl и метрики прогона (чистые функции)."""

import json

import pytest
from builders import checklist, criterion, dialog, result, v3_checklist


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


# --- stability, стоимость, теги, второе мнение ----------------------------------------------


def _results_matrix(n_dialogs: int, n_criteria: int, tweak=None):
    """n_dialogs × n_criteria результатов yes; tweak(dialog, cid) -> новый ответ."""
    results = {}
    for d in range(n_dialogs):
        dlg = f"p1-ru-{d:03d}"
        results[dlg] = {
            f"c{i:02d}": result(tweak(d, i) if tweak and tweak(d, i) else "yes") for i in range(n_criteria)
        }
    return results


def test_stability_192_of_200_is_096() -> None:
    from cqa.domain.agreement import stability

    def tweak(d: int, i: int):
        return "no" if (d, i) in {(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7)} else None

    a = _results_matrix(20, 10)
    b = _results_matrix(20, 10, tweak)  # 8 из 200 различаются

    assert stability(a, b) == 0.96


def test_stability_188_of_200_is_094() -> None:
    from cqa.domain.agreement import stability

    diff = {(d, i) for d in range(10) for i in range(1)} | {(d, i) for d in range(10, 12) for i in range(1)}

    def tweak(d: int, i: int):
        return "no" if (d, i) in diff else None

    assert stability(_results_matrix(20, 10), _results_matrix(20, 10, tweak)) == 0.94


def test_stability_counts_pairs_missing_in_one_run() -> None:
    from cqa.domain.agreement import stability

    a = _results_matrix(2, 2)
    b = {"p1-ru-000": dict(a["p1-ru-000"])}

    assert stability(a, b) == 0.5  # 2 из 4 пар есть только в одном прогоне


def test_run_metrics_cost_calls_model_per_dialog() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    bools = checklist_of_ten_bools()
    for d in range(20):
        dlg = f"p1-ru-{d:03d}"
        dialogs[dlg] = dialog(dlg)
        results[dlg] = {}
        for i in range(10):
            cid = f"c{i:02d}"
            lines.append(gold_line(dlg, cid, ["yes"]))
            results[dlg][cid] = result("yes", calls=1, cost=0.0012, model="qwen3-6")

    metrics = score_run(load_gold(lines, bools), results, dialogs, bools)

    assert metrics.calls == 200
    assert metrics.cost == pytest.approx(0.24)
    assert metrics.cost_per_dialog == pytest.approx(0.012)
    assert metrics.calls_per_dialog == 10
    assert metrics.model == "qwen3-6"


def test_run_metrics_evidence_ok_share() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    bools = checklist_of_ten_bools()
    for d in range(20):
        dlg = f"p1-ru-{d:03d}"
        dialogs[dlg] = dialog(dlg)
        results[dlg] = {}
        for i in range(10):
            cid = f"c{i:02d}"
            lines.append(gold_line(dlg, cid, ["yes"]))
            results[dlg][cid] = result("yes", evFail=(d, i) in {(d0, 0) for d0 in range(20)})

    metrics = score_run(load_gold(lines, bools), results, dialogs, bools)

    assert metrics.evidence_ok == 0.90


def test_run_metrics_tags_recurring_and_single() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    bools = checklist_of_ten_bools()
    tags = {
        ("p1-ru-000", "c00"): "Не назван срок ответа",
        ("p1-ru-001", "c00"): "Не назван срок ответа",  # recurring
        ("p1-ru-000", "c01"): "Долгий ответ",  # single
        ("p1-ru-002", "c05"): "Не поздоровался",  # single
    }
    for d in range(3):
        dlg = f"p1-ru-{d:03d}"
        dialogs[dlg] = dialog(dlg)
        results[dlg] = {}
        for i in range(10):
            cid = f"c{i:02d}"
            lines.append(gold_line(dlg, cid, ["yes"]))
            results[dlg][cid] = result("yes", tag=tags.get((dlg, cid)))

    metrics = score_run(load_gold(lines, bools), results, dialogs, bools)

    assert metrics.tags.recurring == 1
    assert metrics.tags.single == 2


def test_run_metrics_verifier_disagree_and_catch() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines, results, dialogs = [], {}, {}
    bools = checklist_of_ten_bools()
    for d in range(20):
        dlg = f"p1-ru-{d:03d}"
        dialogs[dlg] = dialog(dlg)
        results[dlg] = {}
        for i in range(10):
            cid = f"c{i:02d}"
            lines.append(gold_line(dlg, cid, ["yes"]))
            answer, alt = "yes", None
            if i == 0 and d < 10:
                answer = "no"  # 10 несовпадений
                if d < 6:
                    alt = "yes"  # alt отличается на 6 из них
            elif i == 1 and d < 14:
                alt = "no"  # ещё 14 расхождений с a
            results[dlg][cid] = result(answer, alt=alt)

    metrics = score_run(load_gold(lines, bools), results, dialogs, bools)

    assert metrics.verifier is not None
    assert metrics.verifier.disagree == pytest.approx(0.10)  # 20 из 200
    assert metrics.verifier.catch == pytest.approx(0.60)  # 6 из 10 несовпадений


def test_run_metrics_verifier_block_absent_without_alt() -> None:
    from cqa.domain.agreement import load_gold, score_run

    lines = [gold_line("p1-ru-006", "01", ["yes"])]
    metrics = score_run(
        load_gold(lines, v3_checklist()),
        {"p1-ru-006": {"01": result("yes")}},
        {"p1-ru-006": dialog("p1-ru-006")},
        v3_checklist(),
    )

    assert metrics.verifier is None


def checklist_of_ten_bools():
    return checklist(*[criterion(f"c{i:02d}") for i in range(10)])


# --- gate: пороги и лучший прогон -----------------------------------------------------------


def thresholds(**overrides) -> "object":
    from cqa.domain.agreement import Thresholds

    base = dict(
        gross_recall_min=1.0,
        kz_gap_max_pts=5.0,
        na_precision_min=0.90,
        na_recall_min=0.90,
        stability_min=0.95,
        evidence_ok_min=0.92,
        holdout_agreement_min=0.85,
        baseline_drop_max_pts=3.0,
    )
    base.update(overrides)
    return Thresholds(**base)


def report(**overrides) -> "object":
    from cqa.domain.agreement import Report

    base = dict(
        agree_total=1.0,
        per_lang={"RU": 1.0, "KZ": 0.95},
        per_cid={"01": 1.0},
        missing=0,
        kz_gap_pts=5.0,
        gross_recall={"insult": 1.0, "paid": 1.0, "leak": 1.0},
        gross_recall_lang={"RU": 1.0, "KZ": 1.0},
        gross_missed=[],
        na_precision=1.0,
        na_recall=1.0,
        stability=0.96,
        evidence_ok=0.95,
    )
    base.update(overrides)
    return Report(**base)


def test_gate_passes_clean_report() -> None:
    from cqa.domain.agreement import gate

    assert gate(report(), thresholds(), None) == []


def test_gate_flags_every_threshold() -> None:
    from cqa.domain.agreement import gate

    violations = {
        "gross_recall": report(gross_recall={"leak": 2 / 3}, gross_missed=[("p1-kz-015", "leak")]),
        "na": report(na_recall=0.8),
        "stability": report(stability=0.94),
        "evidence": report(evidence_ok=0.90),
        "holdout": report(holdout_agreement=0.84),
    }
    for name, bad_report in violations.items():
        problems = gate(bad_report, thresholds(), None)
        assert problems, name
        assert all(isinstance(p, str) for p in problems)


def test_gate_gross_miss_names_dialog_and_subquestion() -> None:
    from cqa.domain.agreement import gate

    problems = gate(
        report(gross_recall={"leak": 2 / 3}, gross_missed=[("p1-kz-015", "leak")]),
        thresholds(),
        None,
    )

    assert any("p1-kz-015" in p and "leak" in p for p in problems)


def test_gate_kz_gap_in_points() -> None:
    from cqa.domain.agreement import gate

    problems = gate(report(per_lang={"RU": 1.0, "KZ": 0.85}, kz_gap_pts=15.0), thresholds(), None)

    assert any("15,0" in p and "KZ" in p for p in problems)


def test_gate_baseline_drop_of_four_points() -> None:
    from cqa.domain.agreement import gate

    baseline = report(agree_total=0.97, per_lang={"RU": 1.0, "KZ": 0.97})
    problems = gate(report(agree_total=0.93), thresholds(), baseline)

    assert any("4,0" in p and "пункта" in p for p in problems)


def test_gate_gross_recall_below_baseline() -> None:
    from cqa.domain.agreement import gate

    baseline = report(gross_recall={"leak": 1.0}, gross_recall_lang={"KZ": 1.0})
    problems = gate(report(gross_recall={"leak": 0.875}), thresholds(), baseline)

    assert any("грубы" in p and "лучшего" in p for p in problems)


def test_gate_without_baseline_has_no_drop_messages() -> None:
    from cqa.domain.agreement import gate

    assert gate(report(agree_total=0.93), thresholds(), None) == []


def test_gate_passes_when_within_three_points_of_baseline() -> None:
    from cqa.domain.agreement import gate

    baseline = report(agree_total=0.97, per_lang={"RU": 1.0, "KZ": 0.96})
    problems = gate(
        report(agree_total=0.95, per_lang={"RU": 1.0, "KZ": 0.94}, kz_gap_pts=6.0),
        thresholds(kz_gap_max_pts=10.0),
        baseline,
    )

    assert problems == []


def test_gate_passes_a_drop_of_exactly_three_points() -> None:
    from cqa.domain.agreement import gate

    baseline = report(agree_total=0.90, per_lang={"RU": 1.0, "KZ": 0.90})
    now = report(agree_total=0.87, per_lang={"RU": 0.92, "KZ": 0.87}, kz_gap_pts=5.0)

    assert gate(now, thresholds(), baseline) == []
