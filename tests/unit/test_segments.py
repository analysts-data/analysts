from cqa.domain.events import classify_event
from cqa.domain.ingest import segments

HOLD = "Клиент находится на удержании"
UNHOLD = "Клиент больше не находится на удержании"


def segs(lines: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    who = [w for w, _ in lines]
    kinds = [classify_event(t) if w in ("system", "bot") else None for w, t in lines]
    return segments(who, kinds)


def test_call_with_hold_consultation_and_tail() -> None:
    lines = [
        ("bot", "Здравствуйте! Нажмите 1, чтобы связаться с оператором"),
        ("client", "Один"),
        ("system", "Запись и транскрибирование запущены"),
        ("operator", "Здравствуйте, меня зовут [Имя скрыто]."),
        ("client", "Здравствуйте, не проходит заявка."),
        ("operator", "Сейчас уточню у коллег."),
        ("system", HOLD),
        ("system", "Инициирована консультация с агентом"),
        ("operator", "Коллега, подскажи по заявке."),
        ("operator", "Понял, спасибо."),
        ("system", "Агент вышел из разговора"),
        ("system", UNHOLD),
        ("operator", "Минуту, проверю."),
        ("operator", "минуту,  проверю"),
        ("system", "Клиент завершил разговор"),
        ("operator", "Алло, вы здесь?"),
    ]
    result, warnings = segs(lines)
    assert result == ["pre"] * 3 + ["conv"] * 3 + ["internal"] * 6 + ["conv"] * 3 + ["after"]
    assert warnings == []


def test_without_operator_everything_is_pre_with_warning() -> None:
    result, warnings = segs(
        [("bot", "Здравствуйте!"), ("client", "Есть кто?"), ("system", "Клиент покинул чат")]
    )
    assert result == ["pre"] * 3
    assert any("оператор" in w for w in warnings)


def test_unclosed_window_lasts_to_the_end_with_warning() -> None:
    result, warnings = segs(
        [("operator", "Подождите."), ("system", HOLD), ("client", "Жду."), ("operator", "Ещё минуту.")]
    )
    assert result == ["conv", "internal", "internal", "internal"]
    assert any("окно" in w for w in warnings)


def test_unclosed_window_stops_at_end_event() -> None:
    lines = [
        ("operator", "Подождите."),
        ("system", HOLD),
        ("system", "Клиент завершил разговор"),
        ("operator", "Алло"),
    ]
    result, warnings = segs(lines)
    assert result == ["conv", "internal", "conv", "after"]
    assert any("окно" in w for w in warnings)


def test_repeated_hold_start_does_not_need_two_ends() -> None:
    lines = [
        ("operator", "Подождите."),
        ("system", HOLD),
        ("operator", "Коллега?"),
        ("system", HOLD),
        ("system", UNHOLD),
        ("operator", "Спасибо за ожидание."),
    ]
    result, warnings = segs(lines)
    assert result == ["conv", "internal", "internal", "internal", "internal", "conv"]
    assert warnings == []


def test_operator_reply_after_client_left_chat_is_after() -> None:
    lines = [
        ("bot", "Чем помочь?"),
        ("operator", "Здравствуйте!"),
        ("system", "Клиент покинул чат"),
        ("operator", "Ау?"),
    ]
    result, _ = segs(lines)
    assert result == ["pre", "conv", "conv", "after"]
