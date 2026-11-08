"""Оценки по сотрудникам: поле оператора из записи, CSV назначений, сводка по сотрудникам, раздел отчёта."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from cqa.domain.ingest import ingest_records, parse_operator_csv
from cqa.domain.models import Appeal, Checklist, CriterionResult, Dialog, Line
from cqa.domain.report import UNKNOWN, build_report, operator_card, operators, to_html, to_markdown
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
    dialog("d3", "Борис", "01.11 11:00", res("no", 0)),  # 0, решение поднимает b до 10 → 50
    dialog("d4", None, "01.11 12:00", res("no", 5)),  # 25
    dialog("d5", "Борис", "01.11 13:00"),  # не оценён
]


def appeal(n: int, dlg: str, status: str, to: int | None) -> Appeal:
    return Appeal.model_validate(
        {"id": f"a{n}", "kind": "appeal", "dlg": dlg, "cid": "b", "from": 0, "ask": 10, "to": to,
         "by": "Оператор", "at": "01.11 15:00", "status": status}
    )  # fmt: skip


APPEALS = [appeal(1, "d3", "changed", 10), appeal(2, "d1", "pending", None)]


def test_operators_sorted_by_average_total_ascending_with_unknown_group() -> None:
    rows = operators(CHECKLIST, DIALOGS, APPEALS)

    assert [(r["operator"], r["dialogs"], r["scored"], r["avg_total"]) for r in rows] == [
        (UNKNOWN, 1, 1, 25.0),
        ("Борис", 2, 1, 50.0),
        ("Анна", 2, 2, 87.5),
    ]
    assert UNKNOWN == "Не указан"


def test_operator_row_counts_gross_errors_review_and_open_appeals() -> None:
    anna = operators(CHECKLIST, DIALOGS, APPEALS)[-1]

    assert (anna["gross_errors"], anna["needs_review"], anna["appeals_open"]) == (1, 1, 1)
    assert "dialog_ids" not in anna and "reasons" not in anna


def test_weakest_criteria_are_the_three_lowest_shares_below_full() -> None:
    rows = {r["operator"]: r for r in operators(CHECKLIST, DIALOGS, APPEALS)}

    assert rows["Анна"]["weakest"] == [{"cid": "b", "name": "Решение", "share": 0.75}]
    assert [w["cid"] for w in rows["Борис"]["weakest"]] == ["a"]  # b поднят решением до полного балла


def test_trend_by_day_in_calendar_order_across_months() -> None:
    anna = operators(CHECKLIST, DIALOGS, APPEALS)[-1]

    assert anna["trend"] == [
        {"day": "31.10", "avg_total": 75.0, "dialogs": 1},
        {"day": "01.11", "avg_total": 100.0, "dialogs": 1},
    ]


def test_operator_card_adds_dialog_ids_and_top_reasons() -> None:
    card = operator_card(CHECKLIST, DIALOGS, APPEALS, {}, "Анна")

    assert card is not None
    assert (card["operator"], card["avg_total"], card["dialog_ids"]) == ("Анна", 87.5, ["d1", "d2"])
    assert [(r["tag"], r["dialogs"]) for r in card["reasons"]] == [("Не назван срок", 1)]
    assert operator_card(CHECKLIST, DIALOGS, APPEALS, {}, UNKNOWN)["dialog_ids"] == ["d4"]  # type: ignore[index]
    assert operator_card(CHECKLIST, DIALOGS, APPEALS, {}, "Никто") is None


# --- раздел отчёта «По сотрудникам» ---


def report(dialogs: list[Dialog] = DIALOGS, **filters: str) -> dict[str, Any]:
    return build_report(CHECKLIST, dialogs, APPEALS, {}, at="08.11 07:00", **filters)


def test_report_section_splits_attention_and_best_without_unknown() -> None:
    section = report()["operators"]

    assert [r["operator"] for r in section["attention"]] == ["Борис"]
    assert [r["operator"] for r in section["best"]] == ["Анна"]


def test_report_section_is_empty_when_no_dialog_has_an_operator() -> None:
    plain = [d.model_copy(update={"operator": None}) for d in DIALOGS]
    assert report(plain)["operators"] == {"attention": [], "best": []}


@pytest.mark.parametrize(("name", "n"), [("Анна", 2), (UNKNOWN, 1)])
def test_report_filters_by_operator(name: str, n: int) -> None:
    rep = report(operator=name)
    assert (rep["summary"]["dialogs"], rep["filters"]["operator"]) == (n, name)


def test_report_html_and_md_show_section_and_escape_names() -> None:
    dialogs = [d.model_copy(update={"operator": XSS}) if d.operator == "Борис" else d for d in DIALOGS]
    rep = report(dialogs)

    html, md = to_html(rep), to_markdown(rep)
    assert "По сотрудникам" in html and "По сотрудникам" in md
    assert XSS not in html and "&lt;img src=x onerror=alert(1)&gt;" in html


def test_defence_set_has_four_synthetic_operators() -> None:
    envelope = json.loads(
        (FIXTURES.parent / "e2e" / "fixtures" / "defence_set.json").read_text(encoding="utf-8")
    )
    names = [d.operator for d in ingest(*envelope["data"]["records"])]
    assert None not in names and len(set(names)) == 4
