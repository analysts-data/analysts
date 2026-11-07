import pytest

from cqa.domain.events import classify_event, normalize


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Чат операторға жіберілді", "info"),
        ("Chat transferred to an agent", "info"),
        ("Эскалация на оператора", "info"),
        ("Agent closed the chat", "end"),
        ("Клиент покинул чат", "end"),
        ("Соединение с клиентом прервано", "end"),
        ("Клиент находится на удержании", "hold_start"),
        ("Инициирована консультация с агентом [Имя скрыто]", "consult_start"),
        ("Жазу және транскрипция басталды", "rec_start"),
    ],
)
def test_known_events_are_classified_in_three_languages(text: str, kind: str) -> None:
    assert classify_event(text) == kind


def test_event_with_name_tail_is_recognized() -> None:
    assert classify_event("Оператор закрыл чат [Имя скрыто]") == "end"


def test_case_yo_spaces_and_trailing_punctuation_do_not_matter() -> None:
    assert classify_event("  КЛИЕНТ   покинул   чат!!! ") == "end"
    assert classify_event("Запись и транскрибирование запущены.") == "rec_start"


def test_unknown_event_is_none() -> None:
    assert classify_event("Клиент оценил разговор на 5") is None


def test_normalize_folds_case_yo_spaces_and_trailing_punctuation() -> None:
    assert normalize("  Ёлка,\tЗЕЛЁНАЯ  ёлка?! ") == "елка, зеленая елка"


def test_hold_end_is_not_taken_for_hold_start() -> None:
    assert classify_event("Клиент больше не находится на удержании") == "hold_end"
