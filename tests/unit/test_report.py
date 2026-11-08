"""Отчёт для руководства: числа на фикстуре аналитики (как в web/js), экранирование, пустой набор."""

import json
from typing import Any

from cqa.domain.models import Appeal, Checklist, Dialog
from cqa.domain.report import build_report, to_html, to_markdown
from fakes import FIXTURES

XSS = "<img src=x onerror=alert(1)>"
AT = "08.11 07:00"


def state() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "analytics_state.json").read_text(encoding="utf-8"))
    return data


def report(s: dict[str, Any] | None = None, **filters: str) -> dict[str, Any]:
    s = s or state()
    return build_report(
        Checklist.model_validate(s["checklist"]),
        [Dialog.model_validate(d) for d in s["dialogs"]],
        [Appeal.model_validate(a) for a in s["appeals"]],
        s["owners"],
        at=AT,
        **filters,
    )


def test_key_numbers_count_scores_with_decisions_flags_next_step_review_appeals_and_cost() -> None:
    k = report()["summary"]

    assert (k["dialogs"], k["scored"], k["avg_total"]) == (10, 10, 81.22)
    assert (k["risk"]["dialogs"], k["risk"]["share"]) == (4, 0.4)
    assert [(x["label"], x["n"]) for x in k["risk"]["kinds"]] == [
        ("Оскорбление клиента", 1),
        ("Платная услуга в обход компании", 1),
        ("Раскрытие конфиденциальной информации", 2),
    ]
    # ступень ниже верхней у критерия signal=resolution; апелляция a3 подняла p1-en-006 до полного балла
    assert (k["no_next_step"]["dialogs"], k["no_next_step"]["share"]) == (5, 0.5)
    # расхождение или проваленное основание без решения: p1-en-008/07, p1-kz-003/06; call-024 решён r1
    assert k["needs_review"] == 2
    assert k["open_appeals"] == 1
    assert k["cost"] == {"dialogs": 9, "avg_usd": 0.0134, "avg_s": 42.9}


def test_criteria_average_share_without_na_worst_first_with_names_from_checklist() -> None:
    rows = report()["criteria"]

    assert [r["id"] for r in rows] == ["07", "03", "04", "06", "05", "02", "01"]
    assert rows[0] == {"id": "07", "name": "Завершение", "n": 9, "na": 1, "share": 0.4444}
    assert next(r for r in rows if r["id"] == "03")["na"] == 2
    assert rows[-1]["share"] == 1.0


def test_reasons_top_ten_by_dialogs_with_owner() -> None:
    rows = report()["reasons"]

    assert len(rows) == 10
    assert rows[0] == {
        "tag": "Нет итога и прощания", "dialogs": 5, "owner": "Инструкция", "criteria": ["Завершение"],
    }  # fmt: skip
    assert next(r for r in rows if r["tag"] == "Не назван срок ответа")["dialogs"] == 3
    assert next(r for r in rows if r["tag"] == "Клиенту пришлось переспрашивать")["owner"] == "Не назначено"
    assert [r["dialogs"] for r in rows] == sorted((r["dialogs"] for r in rows), reverse=True)


def test_average_score_and_count_by_channel_and_language() -> None:
    rep = report()

    assert [(r["key"], r["label"], r["n"], r["avg"]) for r in rep["channels"]] == [
        ("chat", "Чат", 9, 81.03),
        ("call", "Звонок", 1, 82.94),
    ]
    assert [(r["key"], r["n"], r["avg"]) for r in rep["langs"]] == [
        ("RU", 6, 76.03),
        ("KZ", 2, 80.5),
        ("EN", 2, 97.5),
    ]


def test_filters_by_language_and_channel() -> None:
    kz = report(lang="kz")
    call = report(ch="call")

    assert (kz["summary"]["dialogs"], kz["summary"]["avg_total"], kz["summary"]["open_appeals"]) == (
        2,
        80.5,
        0,
    )
    assert kz["filters"] == {"lang": "KZ", "ch": None, "operator": None}
    assert (call["summary"]["dialogs"], call["summary"]["open_appeals"]) == (1, 1)


def test_findings_are_plain_russian_sentences_from_the_numbers() -> None:
    findings = report()["findings"]

    assert 3 <= len(findings) <= 5
    assert findings[0] == "Чаще всего баллы теряются на критерии „Завершение“: средняя доля 0,44."
    assert (
        "Грубые нарушения — в 4 из 10 диалогов (40 %), чаще всего «Раскрытие конфиденциальной информации»: 2."
        in (findings)
    )
    assert any(f.startswith("Самая частая причина потери баллов — «Нет итога и прощания»") for f in findings)


def test_html_is_self_contained_a4_print_page_with_bars_and_print_button() -> None:
    page = to_html(report())

    assert page.startswith("<!doctype html>")
    assert "size:A4" in page and "#0E6A55" in page
    assert '<button type="button" class="noprint" onclick="window.print()">Печать / PDF</button>' in page
    assert "<svg" in page and "<link" not in page and "src=" not in page
    assert "81,22" in page and "Завершение" in page and "Нет итога и прощания" in page


def test_markdown_has_findings_numbers_and_tables() -> None:
    md = to_markdown(report())

    assert md.startswith("# Отчёт для руководства\n")
    assert "Чаще всего баллы теряются на критерии „Завершение“" in md
    assert "| Завершение | 9 | 1 | 0,44 |" in md
    assert "| Нет итога и прощания | 5 | Инструкция | Завершение |" in md


def test_html_escapes_criterion_names_tags_owners_and_flag_labels() -> None:
    s = state()
    for c in s["checklist"]["criteria"]:
        c["name"] = XSS
        for q in c.get("questions") or []:
            q["label"] = XSS
    for d in s["dialogs"]:
        for r in d["res"].values():
            if r.get("tag"):
                r["tag"] = XSS
    s["owners"] = {XSS: XSS}

    page = to_html(report(s))

    assert "<img" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_empty_dataset_says_no_scored_dialogs() -> None:
    s = state()
    s["dialogs"], s["appeals"] = [], []

    rep = report(s)

    assert rep["summary"]["scored"] == 0 and rep["summary"]["avg_total"] is None
    assert rep["findings"] == [] and rep["criteria"] == [] and rep["reasons"] == []
    assert "Нет оценённых диалогов" in to_html(rep)
    assert "Нет оценённых диалогов" in to_markdown(rep)
