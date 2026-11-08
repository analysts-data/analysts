import csv
import io
from typing import Any

from cqa.domain.checklist_export import diff, diff_markdown, to_csv, to_html, to_markdown
from cqa.domain.models import Checklist
from fakes import prototype_checklist

XSS = "<img src=x onerror=alert(1)>"


def synthetic(**edits: Any) -> Checklist:
    """Два оценочных критерия 30 и 10 и флаг: доли 75 % и 25 %."""
    data: dict[str, Any] = {
        "version": 7,
        "rules": "Правило один.\nПравило два.",
        "sections": ["Первый раздел", "Второй раздел"],
        "criteria": [
            {"id": "a1", "sec": 0, "name": "Альфа", "type": "bool", "w": 30, "na": True,
             "naCond": "Повода не было.", "text": "Да — сделал; и ещё.", "channel": "all"},
            {"id": "b2", "sec": 1, "name": "Бета", "type": "scale", "w": 10, "na": False,
             "steps": [10, 5, 0], "stepText": {"10": "Полностью", "5": "Частично", "0": "Нет"},
             "text": "Оцените.\nВторая строка.", "call": "На звонке устно.", "channel": "call"},
            {"id": "c3", "sec": 1, "name": "Гамма", "type": "flag", "w": 0, "signal": "risk",
             "questions": [{"k": "x", "label": "Первое", "text": "Пояснение"}, {"k": "y", "label": "Второе"}],
             "text": "Флаг.", "channel": "all"},
        ],
    }  # fmt: skip
    data.update(edits)
    return Checklist.model_validate(data)


def rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.removeprefix("﻿")), delimiter=";"))


def test_csv_opens_in_russian_excel_bom_semicolon_russian_header() -> None:
    text = to_csv(prototype_checklist())

    assert text.startswith("﻿")
    header = rows(text)[0]
    assert header[:5] == ["ID", "Раздел", "Название", "Тип", "Вес"]
    assert "Доля в итоге, % (при всех применимых)" in header
    assert {"N/A", "Условие N/A", "Канал", "Ступени шкалы", "Уточнение для звонка", "Вопросы флага"} <= set(
        header
    )


def test_csv_has_one_row_per_criterion_and_no_version_or_rules_block() -> None:
    cl = prototype_checklist()

    table = rows(to_csv(cl))

    assert [r[0] for r in table[1:]] == [c.id for c in cl.criteria]
    assert all(len(r) == len(table[0]) for r in table)
    assert cl.rules not in to_csv(cl)


def test_csv_share_is_normalised_over_scored_criteria_and_flag_has_no_weight() -> None:
    table = rows(to_csv(synthetic()))
    share = table[0].index("Доля в итоге, % (при всех применимых)")
    weight = table[0].index("Вес")

    assert [r[share] for r in table[1:]] == ["75", "25", ""]
    assert [r[weight] for r in table[1:]] == ["30", "10", ""]


def test_csv_cells_carry_type_na_channel_steps_call_and_questions_in_russian() -> None:
    table = rows(to_csv(synthetic()))
    a, b, c = (dict(zip(table[0], r, strict=True)) for r in table[1:])

    assert (a["Раздел"], a["Тип"], a["N/A"], a["Условие N/A"], a["Канал"]) == (
        "Первый раздел", "Да / Нет", "да", "Повода не было.", "все каналы",
    )  # fmt: skip
    assert a["Что проверяем"] == "Да — сделал; и ещё."  # «;» внутри ячейки не ломает столбцы
    assert (b["Тип"], b["N/A"], b["Условие N/A"], b["Канал"]) == ("Шкала", "нет", "", "звонок")
    assert b["Ступени шкалы"] == "10 — Полностью; 5 — Частично; 0 — Нет"
    assert b["Что проверяем"] == "Оцените.\nВторая строка."
    assert b["Уточнение для звонка"] == "На звонке устно."
    assert c["Тип"] == "Флаг нарушения, без баллов"
    assert c["Вопросы флага"] == "Первое — Пояснение; Второе"


def test_csv_neutralises_formula_cells() -> None:
    cl = synthetic()
    cl.criteria[0].name = "=HYPERLINK(1)"

    assert rows(to_csv(cl))[1][2] == "'=HYPERLINK(1)"


def test_share_of_zero_total_weight_is_zero() -> None:
    cl = synthetic()
    for c in cl.criteria:
        c.w = 0

    assert [r[5] for r in rows(to_csv(cl))[1:]] == ["0", "0", ""]


def test_markdown_document_has_version_rules_sections_weights_steps_na_call_and_questions() -> None:
    md = to_markdown(synthetic())

    assert md.startswith("# Чек-лист v7\n")
    for part in (
        "## Общие правила",
        "Правило один.\nПравило два.",
        "## 1. Первый раздел",
        "## 2. Второй раздел",
        "### a1. Альфа",
        "вес 30, доля в итоге 75 % (при всех применимых)",
        "N/A разрешён: Повода не было.",
        "N/A не разрешён",
        "- 10 — Полностью",
        "На звонке: На звонке устно.",
        "- Первое — Пояснение",
        "Флаг нарушения, без баллов",
    ):
        assert part in md, part
    assert md.index("### a1.") < md.index("## 2. Второй раздел") < md.index("### b2.")


def test_markdown_of_fixture_lists_every_criterion() -> None:
    cl = prototype_checklist()
    md = to_markdown(cl)

    assert all(f"### {c.id}. {c.name}" in md for c in cl.criteria)


def test_html_memo_is_self_contained_printable_and_escaped() -> None:
    cl = synthetic()
    cl.criteria[0].name = XSS
    cl.rules = XSS

    page = to_html(cl)

    assert page.startswith("<!doctype html>")
    assert "<title>Памятка оператора — чек-лист v7</title>" in page
    assert "Чек-лист v7" in page and "Памятка оператора" in page
    assert "@media print" in page and "A4" in page and "#0E6A55" in page
    assert 'onclick="window.print()"' in page and "Печать / PDF" in page
    assert "<img" not in page and "&lt;img src=x onerror=alert(1)&gt;" in page
    assert "http" not in page and "<link" not in page and "<script src" not in page
    assert "75 %" in page and "10 — Полностью" not in page  # ступень — <b>10</b> — текст
    assert "<b>10</b> — Полностью" in page and "Первое — Пояснение" in page


def test_diff_of_identical_checklists_is_empty() -> None:
    assert diff(synthetic(), synthetic(version=8)) == {
        "rules_changed": False,
        "added": [],
        "removed": [],
        "changed": [],
    }


def test_diff_weight_name_section_signal_need_no_reevaluation() -> None:
    new = synthetic()
    new.criteria[0].w, new.criteria[0].name, new.criteria[0].sec = 40, "Альфа-2", 1
    new.criteria[1].signal = "resolution"

    assert diff(synthetic(), new)["changed"] == [
        {"id": "a1", "reevaluate": False, "fields": [
            {"field": "sec", "from": "Первый раздел", "to": "Второй раздел"},
            {"field": "name", "from": "Альфа", "to": "Альфа-2"},
            {"field": "w", "from": 30, "to": 40},
        ]},
        {"id": "b2", "reevaluate": False, "fields": [{"field": "signal", "from": None, "to": "resolution"}]},
    ]  # fmt: skip


def test_diff_meaning_field_change_requires_reevaluation() -> None:
    new = synthetic()
    new.criteria[1].stepText = {"10": "Всё", "5": "Частично", "0": "Нет"}
    new.criteria[2].questions = new.criteria[2].questions[:1]  # type: ignore[index]

    changed = diff(synthetic(), new)["changed"]

    assert [(c["id"], c["reevaluate"], [f["field"] for f in c["fields"]]) for c in changed] == [
        ("b2", True, ["stepText"]),
        ("c3", True, ["questions"]),
    ]


def test_diff_call_change_requires_reevaluation_of_calls() -> None:
    new = synthetic()
    new.criteria[0].call = "Устно."

    [change] = diff(synthetic(), new)["changed"]

    assert change == {
        "id": "a1",
        "reevaluate": True,
        "fields": [{"field": "call", "from": None, "to": "Устно."}],
    }
    md = diff_markdown(synthetic(), new)
    assert "Нужна новая оценка только звонков" in md
    assert "Ждут новой оценки после сохранения: a1 (только звонки)." in md


def test_diff_lists_added_removed_and_rules() -> None:
    old = synthetic()
    new = synthetic(rules="Новые правила.")
    new.criteria = new.criteria[1:] + [new.criteria[0].model_copy(update={"id": "d4", "name": "Дельта"})]

    d = diff(old, new)

    assert d["rules_changed"] is True
    assert d["added"] == [{"id": "d4", "name": "Дельта"}]
    assert d["removed"] == [{"id": "a1", "name": "Альфа"}]
    assert d["changed"] == []


def test_diff_markdown_explains_in_russian_what_is_reevaluated() -> None:
    old = synthetic()
    new = synthetic(rules="Новые правила.", version=8)
    new.criteria[0].w = 40
    new.criteria[1].text = "Оцените по-новому."
    new.criteria = new.criteria[:2]

    md = diff_markdown(old, new)

    assert md.startswith("# Что изменится: v7 → v8\n")
    for part in (
        "## Общие правила изменены",
        "весь чек-лист оценивается заново",
        "Новые правила.",
        "## Удалены",
        "- c3 «Гамма»",
        "### a1 «Альфа»",
        "- вес: 30 → 40",
        "### b2 «Бета»",
        "- текст: «Оцените.\nВторая строка.» → «Оцените по-новому.»",
        "Нужна новая оценка",
    ):
        assert part in md, part


def test_diff_markdown_without_changes_says_so() -> None:
    assert "Изменений нет." in diff_markdown(synthetic(), synthetic(version=8))
