from pathlib import Path
from typing import Any

from cqa.domain.answer import allowed_answer, check, merge_flag, normalize, parse_answer, to_result
from cqa.domain.models import Checklist, Criterion

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CHECKLIST = Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text(encoding="utf-8"))
CRITERIA = {c.id: c for c in CHECKLIST.criteria}
SCALE, BOOL, FLAG = CRITERIA["04"], CRITERIA["01"], CRITERIA["08"]
INSULT, PAID, LEAK = (q.label for q in FLAG.questions or [])


def crit(criterion: Criterion, **changes: Any) -> Criterion:
    return criterion.model_copy(update=changes)


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


def test_scale_result_with_lost_points_keeps_reason_tag_and_better() -> None:
    answer = {
        "reason_ru": "Срок не назван",
        "turn_ids": [9, 10],
        "quote": "Я передам вопрос специалистам",
        "checked_range": [9, 12],
        "answer": "15",
        "tag": "Не назван срок ответа",
        "better": "Ответ придёт за два дня",
    }
    res = to_result(answer, crit(SCALE), ev_fail=False, model="qwen3-6", calls=1, cost=0.002, ms=900)
    assert res.model_dump(exclude_unset=True) == {
        "a": 15,
        "ev": [9, 10],
        "seg": "реплики 9–12",
        "why": "Срок не назван",
        "quote": "Я передам вопрос специалистам",
        "tag": "Не назван срок ответа",
        "better": "Ответ придёт за два дня",
        "evFail": False,
        "model": "qwen3-6",
        "calls": 1,
        "cost": 0.002,
        "ms": 900,
    }


def test_full_marks_drop_tag_and_better() -> None:
    answer = raw("yes", turn_ids=[4], quote="Здравствуйте", tag="лишнее", better="лишнее")
    res = to_result(answer, crit(BOOL), ev_fail=False, model="m", calls=1, cost=0, ms=0)
    assert res.a == "yes" and res.tag is None and res.better is None and res.seg is None


def test_failed_evidence_keeps_answer_without_turns_quote_or_range() -> None:
    answer = raw("no", turn_ids=[4], quote="Добрый вечер", checked_range=[3, 5], tag="Нет приветствия")
    res = to_result(answer, crit(BOOL), ev_fail=True, model="m", calls=2, cost=0, ms=0)
    assert (res.a, res.ev, res.quote, res.seg, res.evFail, res.calls) == ("no", [], None, None, True, 2)
    assert res.tag == "Нет приветствия"


def sub(
    found: bool, reason: str, ids: list[int] | None = None, rng: list[int] | None = None
) -> dict[str, Any]:
    quote = f"цитата {ids[0]}" if ids else ""
    return {
        "reason_ru": reason,
        "turn_ids": ids or [],
        "quote": quote,
        "checked_range": rng,
        "violation_found": found,
    }


def test_flag_merges_found_questions() -> None:
    subs = [(sub(False, "Нет"), False), (sub(True, "Есть", [6]), False), (sub(False, "Нет"), False)]
    res = merge_flag(crit(FLAG), subs, model="m", calls=3, cost=0.3, ms=30)
    assert res.a == {"insult": False, "paid": True, "leak": False}
    assert (res.ev, res.quote, res.tag, res.seg, res.evFail) == (
        [6],
        "цитата 6",
        PAID,
        None,
        False,
    )
    assert res.why == f"{INSULT}: Нет; {PAID}: Есть; {LEAK}: Нет"
    assert (res.model, res.calls, res.cost, res.ms, res.better) == ("m", 3, 0.3, 30, None)


def test_flag_joins_evidence_of_all_found_and_takes_range_of_first_with_one() -> None:
    subs = [
        (sub(True, "А", [9]), False),
        (sub(True, "Б", [2, 9], [2, 4]), False),
        (sub(True, "В", [5], [5, 6]), False),
    ]
    res = merge_flag(crit(FLAG), subs, model="m", calls=3, cost=0, ms=0)
    assert res.ev == [2, 5, 9]
    assert res.quote == "цитата 9"
    assert res.seg == "реплики 2–4"
    assert res.tag == f"{INSULT}, {PAID}, {LEAK}"


def test_flag_question_without_answer_counts_as_not_found_and_marks_flag() -> None:
    subs = [(sub(False, "Нет"), False), (sub(True, "Есть", [6]), False), (None, False)]
    res = merge_flag(crit(FLAG), subs, model="m", calls=2, cost=0, ms=0)
    assert res.a == {"insult": False, "paid": True, "leak": False}
    assert res.ev == [6] and res.evFail is True
    assert f"{LEAK}: не найдено" in (res.why or "")


def test_flag_question_with_failed_evidence_keeps_finding_and_marks_flag() -> None:
    subs = [(sub(True, "Есть", [6]), True), (sub(False, "Нет"), False), (sub(False, "Нет"), False)]
    res = merge_flag(crit(FLAG), subs, model="m", calls=4, cost=0, ms=0)
    assert res.a == {"insult": True, "paid": False, "leak": False}
    assert (res.ev, res.quote, res.evFail, res.tag) == ([], None, True, INSULT)
