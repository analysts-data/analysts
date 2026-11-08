"""Расширенная аналитика на фикстуре аналитики: числа сверены вручную и с отчётом для руководства."""

import json
from datetime import date
from typing import Any

import pytest

from cqa.domain.analytics import MIN_N, NAMES, Filters, build
from cqa.domain.models import Appeal, Checklist, Dialog
from cqa.domain.report import build_report
from fakes import FIXTURES

TODAY = date(2026, 11, 8)
JEV = "jev-test"
MANUAL = "вручную"


def state() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "analytics_state.json").read_text(encoding="utf-8"))
    return data


def run(name: str, s: dict[str, Any] | None = None, by: str | None = None, **filters: Any) -> dict[str, Any]:
    s = s or state()
    return build(
        name,
        Checklist.model_validate(s["checklist"]),
        [Dialog.model_validate(d) for d in s["dialogs"]],
        [Appeal.model_validate(a) for a in s["appeals"]],
        today=TODAY,
        filters=Filters(**filters),
        by=by,
        jev=JEV,
        manual=MANUAL,
    )


def report(**filters: str) -> dict[str, Any]:
    s = state()
    return build_report(
        Checklist.model_validate(s["checklist"]),
        [Dialog.model_validate(d) for d in s["dialogs"]],
        [Appeal.model_validate(a) for a in s["appeals"]],
        s["owners"],
        at="08.11 07:00",
        **filters,
    )


def shifted(ids: tuple[str, ...], at: str) -> dict[str, Any]:
    s = state()
    for d in s["dialogs"]:
        if d["id"] in ids:
            d["at"] = at
    return s


@pytest.mark.parametrize("name", NAMES)
def test_every_answer_has_sample_size_threshold_filters_and_russian_definitions(name: str) -> None:
    out = run(name)

    assert (out["name"], out["n"], out["min_n"]) == (name, 10, MIN_N)
    assert out["filters"] == {
        "lang": None, "ch": None, "operator": None, "product": None, "since": None, "until": None,
    }  # fmt: skip
    assert "low_n" in out["definitions"] and "n" in out["definitions"]
    assert all(isinstance(v, str) and v for v in out["definitions"].values())


def test_trend_by_day_matches_executive_report_key_numbers() -> None:
    out = run("trend")
    k = report()["summary"]

    assert out["by"] == "day"
    [p] = out["points"]
    assert (p["period"], p["n"], p["low_n"], p["avg_total"]) == ("2026-11-07", 10, False, k["avg_total"])
    assert (p["gross"]["k"], p["gross"]["share"]) == (k["risk"]["dialogs"], k["risk"]["share"])
    assert (p["no_next_step"]["k"], p["no_next_step"]["share"]) == (5, k["no_next_step"]["share"])
    assert (p["needs_review"]["k"], p["needs_review"]["share"]) == (k["needs_review"], 0.2)
    shares = {c["id"]: c["share"] for c in report()["criteria"]}
    assert {cid: c["share"] for cid, c in p["criteria"].items()} == shares
    assert p["criteria"]["07"] == {"n": 9, "share": 0.4444, "low_n": False}


def test_trend_by_week_uses_iso_weeks_and_marks_small_periods() -> None:
    out = run("trend", shifted(("p1-ru-003", "p1-ru-009"), "31.10 10:00"), by="week")

    assert [(p["period"], p["start"], p["n"], p["low_n"]) for p in out["points"]] == [
        ("2026-W44", "2026-10-26", 2, True),
        ("2026-W45", "2026-11-02", 8, False),
    ]
    first = out["points"][0]
    assert (first["avg_total"], first["gross"]["k"], first["gross"]["share"]) == (58.0, 1, 0.5)


def test_date_without_year_later_than_today_belongs_to_last_year() -> None:
    s = shifted(("p1-ru-003",), "20.12 10:00")

    assert run("trend", s)["points"][0]["period"] == "2025-12-20"
    assert run("trend", s, since=date(2026, 1, 1))["n"] == 9
    assert run("trend", s, until=date(2025, 12, 31))["n"] == 1


def test_heatmap_by_language_has_cells_with_n_and_low_n_and_matches_report() -> None:
    out = run("heatmap", by="lang")
    langs = report()["langs"]

    assert [(r["key"], r["n"], r["avg_total"]) for r in out["rows"]] == [
        (g["key"], g["n"], g["avg"]) for g in langs
    ]
    ru, kz = out["rows"][0], out["rows"][1]
    assert ru["cells"]["07"] == {"n": 5, "share": 0.4, "low_n": False}
    assert kz["cells"]["07"] == {"n": 2, "share": 0.5, "low_n": True}
    assert [c["id"] for c in out["columns"]] == ["01", "02", "03", "04", "05", "06", "07"]
    assert out["columns"][6] == {"id": "07", "name": "Завершение", "n": 9, "share": 0.4444}


def test_heatmap_defaults_to_operator_and_groups_dialogs_without_value() -> None:
    out = run("heatmap")

    assert out["by"] == "operator"
    assert [(r["key"], r["label"], r["n"]) for r in out["rows"]] == [(None, "Не указан", 10)]


def test_drivers_compare_means_at_max_and_below_with_correlation_and_simulation() -> None:
    out = run("drivers")
    rows = {r["id"]: r for r in out["drivers"]}

    assert [r["id"] for r in out["drivers"]] == ["04", "03", "06", "05", "07", "02", "01"]
    d = rows["07"]
    assert d["n"] == 9
    assert d["at_max"] == {"n": 4, "avg_total": 85.38, "gross": 0.5}
    assert d["below_max"] == {"n": 5, "avg_total": 74.14, "gross": 0.4}
    assert (d["gap"], d["low_n"]) == (11.24, True)
    assert d["r"] == pytest.approx(0.3426, abs=1e-4)
    assert d["lowest"] == {"k": 5, "n": 10, "share": 0.5, "low_n": False}
    assert (d["uplift"], d["avg_total_if_max"]) == (2.71, 83.93)
    assert d["what_if"] == (
        "Если поднять «Завершение» до максимума во всех 9 диалогах, где он применим, "
        "средний итог вырастет на 2,71 балла: с 81,22 до 83,93."
    )
    assert [rows[c]["uplift"] for c in ("04", "03", "06", "05", "02", "01")] == [
        4.34,
        4.0,
        3.23,
        3.0,
        1.5,
        0.0,
    ]
    assert rows["01"]["below_max"] == {"n": 0, "avg_total": None, "gross": None}
    assert (rows["01"]["gap"], rows["01"]["r"]) == (None, None)


def test_distribution_histogram_of_totals_and_answers_per_criterion() -> None:
    out = run("distribution")

    bins = out["totals"]
    assert [(b["lo"], b["hi"]) for b in bins][:2] == [(0, 10), (10, 20)] and len(bins) == 10
    assert [b["n"] for b in bins] == [0, 0, 0, 0, 1, 0, 0, 3, 2, 4]
    assert bins[9]["share"] == 0.4
    crit = {c["id"]: c for c in out["criteria"]}
    assert [(a["a"], a["n"]) for a in crit["07"]["answers"]] == [("yes", 4), ("no", 5), ("na", 1)]
    assert [(a["a"], a["n"]) for a in crit["04"]["answers"]] == [
        (20, 4), (15, 3), (10, 1), (5, 1), (0, 0), ("na", 1),
    ]  # fmt: skip
    assert crit["04"]["n"] == 10 and crit["04"]["answers"][0]["share"] == 0.4
    assert [(a["a"], a["label"], a["n"]) for a in crit["08"]["answers"]][2] == (
        "leak",
        "Раскрытие конфиденциальной информации",
        2,
    )


def test_crosstab_channel_language_product_matches_report_channels() -> None:
    cells = run("crosstab")["cells"]

    assert [(c["ch"], c["lang"], c["product"], c["n"], c["avg_total"]) for c in cells] == [
        ("chat", "RU", None, 5, 74.65),
        ("chat", "KZ", None, 2, 80.5),
        ("chat", "EN", None, 2, 97.5),
        ("call", "RU", None, 1, 82.94),
    ]
    assert cells[0]["gross"] == {"k": 3, "n": 5, "share": 0.6, "low_n": False}
    assert cells[3]["low_n"] is True


def test_appeals_count_decisions_change_share_by_criterion_reviewer_and_median_time() -> None:
    out = run("appeals")

    assert out["summary"] == {
        "filed": 4, "reviews": 1, "pending": 1, "closed": 1, "decided": 3, "changed": 1, "confirmed": 2,
        "changed_share": 0.3333, "low_n": True, "median_hours": 0.56, "timed": 2,
    }  # fmt: skip
    assert out["criteria"] == [
        {"id": "04", "name": "Корректная и полная консультация", "filed": 3, "reviews": 1, "decided": 2,
         "changed": 1, "confirmed": 1, "changed_share": 0.5, "low_n": True},
        {"id": "05", "name": "Эмпатия и клиентоориентированность", "filed": 1, "reviews": 0, "decided": 1,
         "changed": 0, "confirmed": 1, "changed_share": 0.0, "low_n": True},
    ]  # fmt: skip
    assert out["reviewers"] == [
        {"reviewer": "Проверяющий", "decided": 2, "changed": 1, "changed_share": 0.5, "low_n": True,
         "median_hours": 0.56, "timed": 2},
        {"reviewer": "Специалист КК", "decided": 1, "changed": 0, "changed_share": 0.0, "low_n": True,
         "median_hours": None, "timed": 0},
    ]  # fmt: skip


def test_model_signals_second_opinion_evidence_jev_manual_and_cost_by_period() -> None:
    s = state()
    kz = next(d for d in s["dialogs"] if d["id"] == "p1-kz-003")
    kz["res"]["01"]["model"] = MANUAL
    kz["res"]["02"].update(model=JEV, evFail=True)

    out = run("model", s)
    crit = {c["id"]: c for c in out["criteria"]}

    assert crit["04"]["second_opinion"] == {"k": 1, "n": 2, "share": 0.5, "low_n": True}
    assert crit["07"]["second_opinion"] == {"k": 0, "n": 1, "share": 0.0, "low_n": True}
    assert crit["01"]["second_opinion"] == {"k": 0, "n": 0, "share": None, "low_n": True}
    assert crit["06"]["ev_fail"] == {"k": 1, "n": 10, "share": 0.1, "low_n": False}
    assert crit["01"]["manual"] == {"k": 1, "n": 10, "share": 0.1, "low_n": False}
    assert crit["02"]["jev_unsure"] == {"k": 1, "n": 1, "share": 1.0, "low_n": True}
    assert crit["02"]["ev_fail"]["n"] == 9
    k = report()["summary"]["cost"]
    assert out["cost"] == [
        {
            "period": "2026-11-07",
            "n": k["dialogs"],
            "avg_usd": k["avg_usd"],
            "avg_s": k["avg_s"],
            "low_n": False,
        }
    ]


def test_filters_by_language_channel_and_missing_operator_field() -> None:
    assert run("trend", lang="kz")["n"] == 2
    assert run("crosstab", ch="call")["cells"][0]["n"] == 1
    assert run("trend", operator="Иванов")["n"] == 0
    assert run("appeals", lang="kz")["summary"]["filed"] == 0


def test_empty_selection_gives_empty_series_not_errors() -> None:
    for name in NAMES:
        out = run(name, lang="xx")
        assert out["n"] == 0
    assert run("trend", lang="xx")["points"] == []
    assert run("drivers", lang="xx")["drivers"][0]["uplift"] is None
