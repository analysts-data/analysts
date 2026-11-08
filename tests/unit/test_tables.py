"""Общая форма отчёта (заголовок и таблицы) в csv, md и html."""

import csv
import io

from cqa.domain.tables import Doc, Table, to_csv, to_html, to_markdown


def doc(*tables: Table) -> Doc:
    return Doc(kicker="Отчёт", title="Замер", meta="Сформирован 08.11 05:00", tables=list(tables))


SUMMARY = Table("Сводка", ["Показатель", "Значение"], [["Диалогов", "3"], ["Совпадение", "0,91"]], {1})


def test_csv_is_excel_ready_with_bom_semicolons_and_a_block_per_table() -> None:
    body = to_csv(doc(SUMMARY, Table("Пусто", ["A"], [])))

    assert body.startswith("﻿")
    rows = list(csv.reader(io.StringIO(body[1:]), delimiter=";"))
    assert rows[:2] == [["Замер"], ["Сформирован 08.11 05:00"]]
    assert ["Сводка"] in rows and ["Показатель", "Значение"] in rows and ["Совпадение", "0,91"] in rows
    assert ["Пусто"] not in rows


def test_csv_neutralises_formula_cells() -> None:
    body = to_csv(doc(Table("T", ["A"], [["=HYPERLINK(1)"], ["+1"], ["@x"], ["ok"]])))
    rows = list(csv.reader(io.StringIO(body[1:]), delimiter=";"))

    assert ["'=HYPERLINK(1)"] in rows and ["'+1"] in rows and ["'@x"] in rows and ["ok"] in rows


def test_markdown_escapes_pipes_and_line_breaks_in_cells() -> None:
    md = to_markdown(doc(Table("T", ["A", "B"], [["a|b", "c\nd"]])))

    assert md.startswith("# Замер\n")
    assert "## T" in md
    assert "| a\\|b | c d |" in md


def test_html_is_a_self_contained_escaped_a4_page() -> None:
    page = to_html(doc(SUMMARY, Table("T", ["<b>"], [["<script>alert(1)</script>"]])))

    assert page.startswith("<!doctype html>")
    assert "@page{size:A4" in page
    assert "<script>" not in page and "&lt;script&gt;" in page and "&lt;b&gt;" in page
    assert "http" not in page  # ни внешних стилей, ни скриптов
    assert '<td class="num">0,91</td>' in page


def test_document_without_rows_says_there_is_no_data() -> None:
    empty = doc(Table("T", ["A"], []))

    assert "Нет данных" in to_html(empty)
    assert "Нет данных" in to_markdown(empty)
