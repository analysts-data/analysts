from typing import Any

from test_prompt import BOOL, FLAG, SCALE, crit

from cqa.domain.answer import allowed_answer, check, normalize, parse_answer


def test_parse_answer_skips_json_inside_think_and_unwraps_fence() -> None:
    text = (
        '<think>черновик {"answer": "no"}</think>\n'
        '```json\n{"reason_ru": "Поздоровался", "answer": "yes"}\n```'
    )
    assert parse_answer(text) == {"reason_ru": "Поздоровался", "answer": "yes"}


def test_parse_answer_ignores_text_around_object() -> None:
    text = 'Итог проверки: {"reason_ru": "Есть", "violation_found": false} — готово.'
    assert parse_answer(text) == {"reason_ru": "Есть", "violation_found": False}


def test_parse_answer_takes_last_object_with_answer_key() -> None:
    text = '{"answer": "no"} затем пример {"x": 1} и итог {"answer": "yes", "turn_ids": [2]} {"y": {"z": 2}}'
    assert parse_answer(text) == {"answer": "yes", "turn_ids": [2]}


def test_parse_answer_without_json_returns_none() -> None:
    assert parse_answer("Оператор поздоровался, ответ — да") is None


def test_parse_answer_object_without_answer_key_returns_none() -> None:
    assert parse_answer('{"reason_ru": "нет поля ответа"}') is None


def test_normalize_drops_case_punctuation_and_yo() -> None:
    assert (
        normalize("  Здравствуйте!  Меня зовут [Имя скрыто]. Всё_ок ")
        == "здравствуйте меня зовут имя скрыто все_ок"
    )


LINES = {n: f"Реплика {n}." for n in range(1, 10)} | {
    1: "Звонок принят, оператор подключился",
    4: "Здравствуйте! Меня зовут [Имя скрыто].",
}


def raw(answer: Any = "yes", **fields: Any) -> dict[str, Any]:
    return {
        "reason_ru": "Обоснование",
        "turn_ids": [],
        "quote": "",
        "checked_range": None,
        "answer": answer,
    } | fields


def test_quote_with_other_case_and_punctuation_passes() -> None:
    assert check(raw(turn_ids=[4], quote="здравствуйте меня зовут"), crit(BOOL), LINES) == []


def test_system_line_can_be_evidence() -> None:
    assert check(raw(turn_ids=[1], quote="оператор подключился"), crit(BOOL), LINES) == []


def test_missing_line_is_reported_with_its_number() -> None:
    errors = check(raw(turn_ids=[99], quote="что-то"), crit(BOOL), LINES)
    assert any("99" in e for e in errors)


def test_quote_absent_from_cited_line_is_reported() -> None:
    errors = check(raw(turn_ids=[4], quote="Добрый вечер"), crit(BOOL), LINES)
    assert any("цитата" in e for e in errors)


def test_turn_ids_and_quote_come_only_together() -> None:
    assert check(raw(turn_ids=[4]), crit(BOOL), LINES)
    assert check(raw(quote="Здравствуйте"), crit(BOOL), LINES)
    assert check(raw(turn_ids=[4], quote="!!!"), crit(BOOL), LINES)


def test_scale_answer_is_coerced_to_a_step() -> None:
    scale = crit(SCALE)
    assert allowed_answer(raw("15"), scale) == 15
    assert allowed_answer(raw(15.0), scale) == 15
    assert allowed_answer(raw("na"), scale) == "na"
    for bad in (12, 15.5, True, "пятнадцать", None, [15]):
        assert allowed_answer(raw(bad), scale) is None


def test_bool_answer_and_na_follow_criterion_flag() -> None:
    assert allowed_answer(raw("no"), crit(BOOL)) == "no"
    assert allowed_answer(raw("na"), crit(BOOL)) is None
    assert allowed_answer(raw("na"), crit(BOOL, na=True, naCond="Условие.")) == "na"
    assert allowed_answer(raw(20), crit(BOOL)) is None


def test_off_scale_step_lists_allowed_values() -> None:
    errors = check(raw(12, turn_ids=[4], quote="Здравствуйте"), crit(SCALE), LINES)
    assert any("20, 15, 10, 5, 0" in e for e in errors)


def test_forbidden_na_is_reported() -> None:
    errors = check(raw("na"), crit(BOOL), LINES)
    assert any("N/A" in e and "не разрешён" in e for e in errors)


def test_lost_points_require_turn_or_checked_range() -> None:
    errors = check(raw("no"), crit(BOOL), LINES)
    assert any("checked_range" in e for e in errors)
    assert check(raw("no", checked_range=[3, 5]), crit(BOOL), LINES) == []
    assert check(raw(15), crit(SCALE), LINES)
    assert check(raw(15, turn_ids=[4], quote="меня зовут"), crit(SCALE), LINES) == []
    assert check(raw(20), crit(SCALE), LINES) == []


def test_checked_range_holds_two_existing_ordered_lines() -> None:
    for bad in ([5, 3], [3, 99], [3], "3-5"):
        assert check(raw("no", checked_range=bad), crit(BOOL), LINES)


def test_empty_reason_is_reported() -> None:
    errors = check(raw(reason_ru="  "), crit(BOOL), LINES)
    assert any("reason_ru" in e for e in errors)


def test_found_violation_needs_turn_and_quote_while_absent_one_needs_nothing() -> None:
    flag = crit(FLAG)
    found = {"reason_ru": "Есть", "checked_range": [3, 5], "violation_found": True}
    assert check(found, flag, LINES, sub=True)
    assert check(found | {"turn_ids": [4], "quote": "меня зовут"}, flag, LINES, sub=True) == []
    assert check({"reason_ru": "Нет", "violation_found": False}, flag, LINES, sub=True) == []
    assert check({"reason_ru": "Нет", "violation_found": "нет"}, flag, LINES, sub=True)


def test_malformed_turn_ids_are_errors_not_crashes() -> None:
    for bad in ([[4]], ["4"], [True], 4):
        assert check(raw(turn_ids=bad, quote="Здравствуйте"), crit(BOOL), LINES)
