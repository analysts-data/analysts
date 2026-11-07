"""Обезличивание диалога: шаблоны персональных данных (задачи 5.1–5.5)."""

from __future__ import annotations

import json
from pathlib import Path

from cqa.domain.anonymize import anonymize
from cqa.domain.models import Dialog, Fold, Line


def anonymized(text: str) -> str:
    """Текст единственной реплики клиента после обезличивания."""
    dialog = Dialog(
        id="d-1",
        ch="chat",
        lang="RU",
        at="07.11 13:49",
        lines=[Line(n=1, t="00:01", who="client", text=text)],
    )
    return anonymize(dialog).lines[0].text


def test_email_is_replaced_with_label() -> None:
    assert anonymized("мой адрес aliya@mail.kz, напишите мне") == ("мой адрес [ПОЧТА], напишите мне")


def test_kz_iban_is_replaced_with_label() -> None:
    assert anonymized("перевод на счёт KZ86125KZT5004100100 оформлен") == (
        "перевод на счёт [НОМЕР_СЧЁТА] оформлен"
    )


def test_card_number_is_replaced_with_label() -> None:
    assert anonymized("карта 4400 4301 2345 6789 привязана") == ("карта [НОМЕР_КАРТЫ] привязана")


def test_iin_and_phone_are_replaced_with_labels() -> None:
    assert anonymized("мой ИИН 900101300123, телефон +7 701 123 45 67") == (
        "мой ИИН [ДАННЫЕ_ИДЕНТИФИКАЦИИ], телефон [ТЕЛЕФОН]"
    )


def test_phone_with_eight_and_parens_is_replaced() -> None:
    assert anonymized("наберу с номера 8 (701) 123-45-67") == "наберу с номера [ТЕЛЕФОН]"


def test_organizer_masks_are_untouched() -> None:
    text = "[Имя скрыто], [Данные идентификации скрыты], [Номер скрыт]"
    assert anonymized(text) == text


def test_brands_tickers_and_amounts_are_untouched() -> None:
    text = "Freedom Broker: акции AAPL, консультация 5 000 тенге"
    assert anonymized(text) == text


def anonymized_texts(*entries: tuple[str, str]) -> list[str]:
    """Тексты реплик диалога после обезличивания; entries — пары (who, text)."""
    lines = [
        Line(n=i + 1, t="00:01", who=who, text=text)  # type: ignore[arg-type]
        for i, (who, text) in enumerate(entries)
    ]
    dialog = Dialog(id="d-1", ch="chat", lang="RU", at="07.11 13:49", lines=lines)
    return [line.text for line in anonymize(dialog).lines]


def test_operator_name_from_hint_replaces_all_mentions() -> None:
    out = anonymized_texts(
        ("operator", "Здравствуйте, меня зовут алия, слушаю вас"),
        ("client", "добрый день"),
        ("operator", "Алия на связи"),
    )
    assert out[0] == "Здравствуйте, меня зовут [ИМЯ_ОПЕРАТОРА], слушаю вас"
    assert out[2] == "[ИМЯ_ОПЕРАТОРА] на связи"


def test_client_name_from_answer_and_fuzzy_variant() -> None:
    out = anonymized_texts(
        ("operator", "Как к вам обращаться?"),
        ("client", "пирас"),
        ("operator", "Тирас, подождите минуту"),
    )
    assert out[1] == "[ИМЯ_КЛИЕНТА_1]"
    assert out[2] == "[ИМЯ_КЛИЕНТА_1], подождите минуту"


def test_name_and_surname_become_one_label() -> None:
    out = anonymized_texts(("client", "меня зовут иван петров"))
    assert out[0] == "меня зовут [ИМЯ_КЛИЕНТА_1]"


def test_clients_are_numbered_and_hints_work_in_kz_and_en() -> None:
    out = anonymized_texts(
        ("client", "меня зовут иван петров"),
        ("client", "менің атым айгүл"),
        ("operator", "my name is john"),
    )
    assert out[0] == "меня зовут [ИМЯ_КЛИЕНТА_1]"
    assert out[1] == "менің атым [ИМЯ_КЛИЕНТА_2]"
    assert out[2] == "my name is [ИМЯ_ОПЕРАТОРА]"


def test_stop_word_is_not_captured_as_second_name_word() -> None:
    out = anonymized_texts(("client", "моё имя алия и я ваш клиент"))
    assert out[0] == "моё имя [ИМЯ_КЛИЕНТА_1] и я ваш клиент"


def _prototype_dialog(dialog_id: str) -> Dialog:
    dialogs = [
        Dialog.model_validate(raw)
        for raw in json.loads(Path("tests/fixtures/dialogs_prototype.json").read_text())
    ]
    return next(d for d in dialogs if d.id == dialog_id)


def test_anonymize_preserves_structure_of_prototype_call() -> None:
    """call-024: меняется только текст, вход не меняется, результат детерминирован."""
    dialog = _prototype_dialog("call-024")
    untouched = dialog.model_copy(deep=True)

    first = anonymize(dialog)
    second = anonymize(dialog)

    assert first == second
    assert dialog == untouched
    assert first is not dialog
    assert len(first.lines or []) == len(dialog.lines or [])
    for source, anonymized_line in zip(dialog.lines or [], first.lines or [], strict=True):
        assert type(source) is type(anonymized_line)
        for field in ("n", "who", "seg", "t", "s"):
            if hasattr(source, field):
                assert getattr(anonymized_line, field) == getattr(source, field)
        if isinstance(source, Fold):
            assert anonymized_line == source
