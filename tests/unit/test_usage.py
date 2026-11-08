"""Метрики использования: очистка props, сводка по экранам, воронки, CSV, лимит запросов."""

from datetime import UTC, datetime, timedelta
from typing import Any

from cqa.domain.usage import UsageEvent, aggregate, clean_props, funnel, to_csv
from cqa.services.telemetry import TokenBucket

T0 = datetime(2026, 11, 8, 4, 0, tzinfo=UTC)  # 09:00 в Астане


def ev(event: str, s: float, actor: str = "qa", page: str = "queue", **props: Any) -> UsageEvent:
    return UsageEvent(
        at=T0 + timedelta(seconds=s), actor=actor, role="qa", event=event, page=page, props=props
    )


def test_search_query_and_dialogue_text_are_reduced_to_length() -> None:
    props = clean_props({"q": "Иванов просрочка", "text": "Клиент: верните деньги", "has_result": False})

    assert props == {"len": 16, "has_result": False}


def test_unknown_keys_free_text_and_nested_values_are_dropped() -> None:
    props = clean_props(
        {
            "act": "decide",
            "value": "два слова",
            "kind": {"x": 1},
            "comment": "нет",
            "ms": 1200,
            "id": "call-024",
        }
    )

    assert props == {"act": "decide", "ms": 1200, "id": "call-024"}


def test_funnel_counts_converted_pairs_and_median_from_last_open() -> None:
    events = [
        ev("dialog_open", 0, id="d1"),
        ev("dialog_open", 100, id="d1"),  # открыл снова — время от последнего открытия
        ev("appeal_submit", 160, id="d1"),
        ev("dialog_open", 0, actor="op", id="d2"),
        ev("appeal_submit", 20, actor="op", id="d2"),
        ev("dialog_open", 5, id="d3"),  # не дошёл до апелляции
        ev("appeal_submit", 1, id="d4"),  # без открытия — не в воронке
    ]

    assert funnel(events, "dialog_open", "appeal_submit") == {
        "started": 3,
        "converted": 2,
        "rate": 0.667,
        "median_s": 40.0,
    }


def test_empty_funnel_has_no_rate() -> None:
    assert funnel([], "appeal_open", "decision_submit") == {
        "started": 0,
        "converted": 0,
        "rate": None,
        "median_s": None,
    }


def test_aggregate_users_screens_actions_errors_and_outputs() -> None:
    events = [
        ev("page_view", 0),
        ev("action", 1, act="open"),
        ev("action", 2, act="open"),
        ev("action", 3, act="reviewed"),
        ev("time_on_page", 4, ms=1000),
        ev("time_on_page", 5, ms=3000),
        ev("page_view", 6, actor="op", page="card"),
        ev("time_on_page", 7, actor="op", page="card", ms=500),
        ev("error_shown", 8, page="card", code="run_failed"),
        ev("export", 9, page="checklist", kind="csv"),
        ev("report_open", 10, page="analytics", kind="html"),
        ev("page_view", 86400, actor="op"),  # следующий день
    ]

    usage = aggregate(events)

    assert usage["events"] == 12
    assert usage["active_users"] == [{"day": "2026-11-08", "users": 2}, {"day": "2026-11-09", "users": 1}]
    assert usage["screens"][0] == {"page": "queue", "events": 7, "views": 2, "median_ms": 2000}
    assert {"page": "card", "events": 3, "views": 1, "median_ms": 500} in usage["screens"]
    assert usage["actions"] == [{"act": "open", "n": 2}, {"act": "reviewed", "n": 1}]
    assert usage["errors"] == [{"page": "card", "code": "run_failed", "n": 1}]
    assert usage["exports"] == [{"kind": "csv", "n": 1}]
    assert usage["reports"] == [{"kind": "html", "n": 1}]
    assert [f["name"] for f in usage["funnels"]] == [
        "Открыл диалог → подал апелляцию",
        "Открыл апелляцию → принял решение",
    ]


def test_csv_is_excel_long_table_with_decimal_comma() -> None:
    events = [ev("dialog_open", 0, id="d1"), ev("appeal_submit", 3, id="d1"), ev("dialog_open", 0, id="d2")]

    text = to_csv(aggregate(events))

    assert text.startswith("﻿Раздел;Ключ;Показатель;Значение\r\n")
    assert "funnels;Открыл диалог → подал апелляцию;rate;0,5\r\n" in text
    assert "active_users;2026-11-08;users;1\r\n" in text


def test_token_bucket_refills_with_time() -> None:
    now = [0.0]
    bucket = TokenBucket(capacity=2, rate=1.0, clock=lambda: now[0])

    assert [bucket.take("a"), bucket.take("a"), bucket.take("a"), bucket.take("b")] == [
        True,
        True,
        False,
        True,
    ]
    now[0] = 1.0
    assert bucket.take("a") is True
    assert bucket.take("a") is False
