"""Оценки для команды качества в Excel: wide и long на фикстуре аналитики, решения, экранирование."""

import csv
import io
import json
from typing import Any

from cqa.domain.models import Appeal, Checklist, Dialog
from cqa.domain.scores_export import to_csv
from fakes import FIXTURES

FIXED = [
    "ID", "Название", "Канал", "Язык", "Дата", "Итог", "Грубое нарушение", "Виды нарушений",
    "Нужна проверка", "Проверен",
]  # fmt: skip
LONG = [
    "ID диалога", "ID критерия", "Критерий", "Ответ", "Доля", "Обоснование", "Реплики-основания",
    "Причина", "Как сказать лучше", "Модель", "Решение проверяющего",
]  # fmt: skip


def state() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "analytics_state.json").read_text(encoding="utf-8"))
    return data


def export(s: dict[str, Any] | None = None, **kw: str) -> str:
    s = s or state()
    return to_csv(
        Checklist.model_validate(s["checklist"]),
        [Dialog.model_validate(d) for d in s["dialogs"]],
        [Appeal.model_validate(a) for a in s["appeals"]],
        **kw,  # type: ignore[arg-type]
    )


def table(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.removeprefix("﻿")), delimiter=";"))


def by_id(text: str) -> dict[str, dict[str, str]]:
    head, *rows = table(text)
    return {r[0]: dict(zip(head, r, strict=True)) for r in rows}


def test_csv_opens_in_russian_excel_bom_and_semicolon() -> None:
    text = export()

    assert text.startswith("﻿ID;Название;Канал;")


def test_wide_has_one_row_per_dialog_and_a_column_per_criterion_named_from_checklist() -> None:
    s = state()
    head, *rows = table(export(s))

    assert head == FIXED + [c["name"] for c in s["checklist"]["criteria"]]
    assert [r[0] for r in rows] == [d["id"] for d in s["dialogs"]]


def test_wide_row_carries_dialog_fields_and_answers_in_russian() -> None:
    call = by_id(export())["call-024"]

    assert (call["Название"], call["Канал"], call["Язык"], call["Дата"]) == (
        "Звонок 024",
        "Звонок",
        "RU",
        "07.11 14:52",
    )
    assert call["Итог"] == "82,94"
    assert (call["Установление контакта"], call["Выявление потребности"], call["Завершение"]) == (
        "Да",
        "N/A",
        "Нет",
    )
    assert call["Корректная и полная консультация"] == "15 из 20"
    assert call["Грубые ошибки"] == "Нарушений нет"
    assert by_id(export())["p1-ru-022"]["Название"] == "p1-ru-022"  # без title — id, как в интерфейсе


def test_wide_total_and_answer_follow_the_reviewer_decision() -> None:
    row = by_id(export())["p1-en-006"]  # апелляция a3 подняла 04 с 15 до 20

    assert (row["Итог"], row["Корректная и полная консультация"]) == ("100,00", "20 из 20")


def test_wide_flags_review_and_reviewed_columns() -> None:
    rows = by_id(export())

    rude = rows["p1-ru-029"]
    assert (rude["Грубое нарушение"], rude["Виды нарушений"], rude["Проверен"]) == (
        "да",
        "Оскорбление клиента",
        "да",
    )
    assert (rows["call-024"]["Грубое нарушение"], rows["call-024"]["Виды нарушений"]) == ("нет", "")
    # расхождение или проваленное основание без решения; у call-024 расхождение решено r1
    assert [i for i, r in rows.items() if r["Нужна проверка"] == "да"] == ["p1-en-008", "p1-kz-003"]
    assert rows["call-024"]["Проверен"] == "нет"


def test_wide_dialog_without_results_has_empty_total_and_waiting_answers() -> None:
    s = state()
    s["dialogs"][0]["res"] = {}

    row = by_id(export(s))["call-024"]

    assert row["Итог"] == ""
    assert row["Завершение"] == "ждёт оценки"


def test_long_has_a_row_per_evaluated_dialog_and_criterion() -> None:
    s = state()
    s["dialogs"][1]["res"] = {}  # p1-ru-022 не оценён — строк нет
    head, *rows = table(export(s, shape="long"))

    assert head == LONG
    assert len(rows) == 9 * len(s["checklist"]["criteria"])
    assert "p1-ru-022" not in {r[0] for r in rows}


def test_long_row_carries_reasoning_evidence_tag_better_model_and_decision() -> None:
    s = state()
    r = s["dialogs"][-1]["res"]["04"]
    r.update(ev=[7, 9], model="qwen3")
    rows = {(x[0], x[1]): dict(zip(LONG, x, strict=True)) for x in table(export(s, shape="long"))[1:]}

    row = rows[("p1-en-006", "04")]
    assert (row["Критерий"], row["Ответ"], row["Доля"]) == (
        "Корректная и полная консультация",
        "20 из 20",
        "1,00",
    )
    assert row["Обоснование"] == r["why"]
    assert (row["Реплики-основания"], row["Причина"], row["Модель"]) == (
        "7, 9",
        "Не назван срок ответа",
        "qwen3",
    )
    assert row["Как сказать лучше"] == r["better"]
    assert row["Решение проверяющего"] == (
        "Изменено: 15 из 20 → 20 из 20. Регламент запрещает называть срок, следующий шаг дан полностью. "
        "(Проверяющий)"
    )
    call = rows[("call-024", "04")]  # ожидающая апелляция a1 — не решение, решение — проверка r1
    assert (call["Ответ"], call["Доля"]) == ("15 из 20", "0,75")
    assert (
        call["Решение проверяющего"]
        == "Подтверждено: 15 из 20. Срок по регламенту не называется (Специалист КК)"
    )
    assert (rows[("call-024", "02")]["Доля"], rows[("call-024", "02")]["Решение проверяющего"]) == ("", "")
    assert rows[("call-024", "08")]["Доля"] == ""


def test_filters_by_language_and_channel() -> None:
    assert list(by_id(export(lang="kz"))) == ["p1-kz-015", "p1-kz-003"]
    assert list(by_id(export(ch="call"))) == ["call-024"]
    assert {r[0] for r in table(export(shape="long", ch="call"))[1:]} == {"call-024"}


def test_formula_cells_are_neutralised() -> None:
    s = state()
    s["dialogs"][0]["res"]["07"]["why"] = '=HYPERLINK("http://evil.test","x")'
    s["dialogs"][0]["title"] = "+7 700 000"
    s["checklist"]["criteria"][0]["name"] = "@SUM(A1)"

    long = {(x[0], x[1]): x for x in table(export(s, shape="long"))[1:]}
    head, *_ = table(export(s))

    assert long[("call-024", "07")][5] == '\'=HYPERLINK("http://evil.test","x")'
    assert by_id(export(s))["call-024"]["Название"] == "'+7 700 000"
    assert head[len(FIXED)] == "'@SUM(A1)"
