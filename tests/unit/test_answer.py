from cqa.domain.answer import normalize, parse_answer


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
