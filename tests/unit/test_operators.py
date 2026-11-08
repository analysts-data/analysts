"""Оценки по сотрудникам: поле оператора из записи, CSV назначений, сводка по сотрудникам, раздел отчёта."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from cqa.domain.ingest import ingest_records, parse_operator_csv
from cqa.domain.models import Appeal, Checklist, CriterionResult, Dialog, Line
from cqa.domain.report import (
    DEFINITIONS,
    MIN_SCORED,
    UNKNOWN,
    build_report,
    ci95,
    operator_card,
    operators,
    to_html,
    to_markdown,
)
from fakes import FIXTURES

XSS = "<img src=x onerror=alert(1)>"


def record(cid: str = "syn-1", **extra: Any) -> dict[str, Any]:
    return {
        "conversation_id": cid,
        "channel": "agent chat",
        "language": "ru",
        "transcript": [
            {"timestamp": "00:01", "speaker": "client", "text": "Здравствуйте"},
            {"timestamp": "00:05", "speaker": "operator", "text": "Добрый день"},
        ],
        **extra,
    }


def ingest(*records: dict[str, Any]) -> list[Dialog]:
    result, _ = ingest_records(
        records, group_id="T", now=datetime(2026, 11, 8, tzinfo=UTC), shift_s=0, shift_paused_s=0
    )
    return result.dialogs


# --- поле оператора из записи организаторов ---


def test_ingest_takes_first_non_empty_operator_field() -> None:
    [d] = ingest(record(operator="  ", agent_name=" Тестовый Сотрудник ", employee="Другой"))
    assert d.operator == "Тестовый Сотрудник"


def test_ingest_maps_numeric_agent_id_and_tolerates_missing_field() -> None:
    a, b = ingest(record("a", agent_id=1042, extra_field={"x": 1}), record("b"))
    assert (a.operator, b.operator) == ("1042", None)


# --- CSV назначений ---


def test_operator_csv_semicolon_with_bom_header_and_blank_lines() -> None:
    text = "﻿conversation_id;operator\n\np1;Сотрудник А\np2;\n"
    assert parse_operator_csv(text) == [("p1", "Сотрудник А"), ("p2", None)]


def test_operator_csv_comma_and_quotes() -> None:
    assert parse_operator_csv('p1,"Б, старший"\r\np2, В \n') == [("p1", "Б, старший"), ("p2", "В")]


# --- сводка по сотрудникам ---

CHECKLIST = Checklist.model_validate(
    {
        "version": 1,
        "rules": "",
        "sections": ["Раздел"],
        "criteria": [
            {"id": "a", "sec": 0, "name": "Приветствие", "type": "bool", "w": 50, "text": "…"},
            {"id": "b", "sec": 0, "name": "Решение", "type": "scale", "w": 50, "steps": [10, 5, 0],
             "text": "…"},
            {
                "id": "f", "sec": 0, "name": "Грубые", "type": "flag", "w": 0, "signal": "risk", "text": "…",
                "questions": [{"k": "insult", "label": "Оскорбление"}],
            },
        ],
    }
)  # fmt: skip


def res(
    a: str, b: int, *, insult: bool = False, tag: str | None = None, ev_fail: bool = False
) -> dict[str, Any]:
    return {
        "a": CriterionResult(a=a),
        "b": CriterionResult(a=b, tag=tag, evFail=ev_fail),
        "f": CriterionResult(a={"insult": insult}),
    }


def dialog(did: str, op: str | None, at: str, results: dict[str, Any] | None = None) -> Dialog:
    return Dialog(
        id=did, ch="chat", lang="RU", at=at, operator=op, res=results or {},
        lines=[Line(n=1, t="00:01", who="operator", text="Добрый день")],
    )  # fmt: skip


DIALOGS = [
    dialog("d1", "Анна", "31.10 10:00", res("yes", 5, insult=True, tag="Не назван срок")),  # 75
    dialog("d2", "Анна", "01.11 09:00", res("yes", 10, ev_fail=True)),  # 100
    *(dialog(f"a{i}", "Анна", "01.11 10:00", res("yes", 10)) for i in range(3, 6)),  # 100 × 3
    dialog("d3", "Борис", "01.11 11:00", res("no", 0)),  # 0, решение поднимает b до 10 → 50
    *(dialog(f"b{i}", "Борис", "01.11 11:00", res("no", 10)) for i in range(2, 6)),  # 50 × 4
    dialog("d5", "Борис", "01.11 13:00"),  # не оценён
    *(dialog(f"v{i}", "Вера", "01.11 14:00", res("yes", 5)) for i in range(1, 4)),  # 75 × 3
    dialog("d4", None, "01.11 12:00", res("no", 5)),  # 25
]


def appeal(n: int, dlg: str, status: str, to: int | None) -> Appeal:
    return Appeal.model_validate(
        {"id": f"a{n}", "kind": "appeal", "dlg": dlg, "cid": "b", "from": 0, "ask": 10, "to": to,
         "by": "Оператор", "at": "01.11 15:00", "status": status}
    )  # fmt: skip


APPEALS = [appeal(1, "d3", "changed", 10), appeal(2, "d1", "pending", None)]


def rows_by_name() -> dict[str, dict[str, Any]]:
    return {r["operator"]: r for r in operators(CHECKLIST, DIALOGS, APPEALS)}


def test_only_operators_with_enough_scored_dialogs_are_ranked_lowest_average_first() -> None:
    rows = operators(CHECKLIST, DIALOGS, APPEALS)

    assert [(r["operator"], r["dialogs"], r["n"], r["avg_total"], r["ranked"]) for r in rows] == [
        ("Борис", 6, 5, 50.0, True),
        ("Анна", 5, 5, 95.0, True),
        ("Вера", 3, 3, 75.0, False),
        (UNKNOWN, 1, 1, 25.0, False),
    ]
    assert [r["reason"] for r in rows] == [
        None,
        None,
        f"недостаточно данных (n=3, нужно ≥{MIN_SCORED})",
        "сотрудник не указан",
    ]
    assert (UNKNOWN, MIN_SCORED) == ("Не указан", 5)


def test_spread_is_sample_sd_and_student_95_interval_clipped_to_scale() -> None:
    rows = rows_by_name()

    assert (rows["Анна"]["sd"], rows["Анна"]["ci95"]) == (11.18, [81.12, 100.0])  # 95 ± 2,776·11,18/√5
    assert (rows["Борис"]["sd"], rows["Борис"]["ci95"]) == (0.0, [50.0, 50.0])
    assert (rows[UNKNOWN]["sd"], rows[UNKNOWN]["ci95"]) == (None, None)  # n = 1


def test_ci95_beyond_the_table_uses_the_student_expansion() -> None:
    assert ci95([0.0, 100.0] * 20) == (50.64, [33.81, 66.19])  # t(0,975; 39) = 2,0227
    assert ci95([80.0]) == (None, None)


def test_definitions_name_the_interval_and_the_threshold() -> None:
    assert "Стьюдент" in DEFINITIONS["ci95"]
    assert str(MIN_SCORED) in DEFINITIONS["ranked"]


def test_operator_row_counts_gross_errors_review_and_open_appeals() -> None:
    anna = rows_by_name()["Анна"]

    assert (anna["gross_errors"], anna["needs_review"], anna["appeals_open"]) == (1, 1, 1)
    assert "dialog_ids" not in anna and "reasons" not in anna


def test_weakest_criteria_are_the_three_lowest_shares_below_full() -> None:
    rows = rows_by_name()

    assert rows["Анна"]["weakest"] == [{"cid": "b", "name": "Решение", "share": 0.9}]
    assert [w["cid"] for w in rows["Борис"]["weakest"]] == ["a"]  # b поднят решением до полного балла


def test_trend_by_day_in_calendar_order_across_months() -> None:
    assert rows_by_name()["Анна"]["trend"] == [
        {"day": "31.10", "avg_total": 75.0, "dialogs": 1},
        {"day": "01.11", "avg_total": 100.0, "dialogs": 4},
    ]


def test_operator_card_adds_dialog_ids_and_top_reasons() -> None:
    card = operator_card(CHECKLIST, DIALOGS, APPEALS, {}, "Анна")

    assert card is not None
    assert (card["operator"], card["avg_total"]) == ("Анна", 95.0)
    assert card["dialog_ids"] == ["d1", "d2", "a3", "a4", "a5"]
    assert [(r["tag"], r["dialogs"]) for r in card["reasons"]] == [("Не назван срок", 1)]
    assert operator_card(CHECKLIST, DIALOGS, APPEALS, {}, UNKNOWN)["dialog_ids"] == ["d4"]  # type: ignore[index]
    assert operator_card(CHECKLIST, DIALOGS, APPEALS, {}, "Никто") is None


# --- раздел отчёта «По сотрудникам» ---


def report(dialogs: list[Dialog] = DIALOGS, **filters: str) -> dict[str, Any]:
    return build_report(CHECKLIST, dialogs, APPEALS, {}, at="08.11 07:00", **filters)


def test_report_section_splits_attention_and_strengths_among_ranked_only() -> None:
    section = report()["operators"]

    assert [r["operator"] for r in section["attention"]] == ["Борис"]
    assert [r["operator"] for r in section["strengths"]] == ["Анна"]


def test_report_section_is_empty_without_two_ranked_operators() -> None:
    plain = [d.model_copy(update={"operator": None}) for d in DIALOGS]
    alone = [d for d in DIALOGS if d.operator != "Борис"]  # ранжирована одна Анна — сравнивать не с кем
    assert report(plain)["operators"] == report(alone)["operators"] == {"attention": [], "strengths": []}


@pytest.mark.parametrize(("name", "n"), [("Анна", 5), (UNKNOWN, 1)])
def test_report_filters_by_operator(name: str, n: int) -> None:
    rep = report(operator=name)
    assert (rep["summary"]["dialogs"], rep["filters"]["operator"]) == (n, name)


def test_report_html_and_md_use_attention_wording_and_escape_names() -> None:
    dialogs = [d.model_copy(update={"operator": XSS}) if d.operator == "Борис" else d for d in DIALOGS]
    rep = report(dialogs)

    html, md = to_html(rep), to_markdown(rep)
    for text in (html, md):
        assert "По сотрудникам: требуют внимания" in text and "По сотрудникам: сильные стороны" in text
        assert "лучш" not in text.lower() and "рейтинг" not in text.lower()
    assert XSS not in html and "&lt;img src=x onerror=alert(1)&gt;" in html


def test_defence_set_has_four_synthetic_operators() -> None:
    envelope = json.loads(
        (FIXTURES.parent / "e2e" / "fixtures" / "defence_set.json").read_text(encoding="utf-8")
    )
    names = [d.operator for d in ingest(*envelope["data"]["records"])]
    assert None not in names and len(set(names)) == 4
