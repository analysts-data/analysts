"""Обезличивание диалога: шаблоны персональных данных (задачи 5.1–5.5).

Пока bootstrap-harness не слил `src/cqa/domain/models.py`, тесты собирают
минимальные подстановки `Line` и `Dialog` по design/contract.md.
"""

from __future__ import annotations

from pydantic import BaseModel

from cqa.domain.anonymize import anonymize


class Line(BaseModel):
    """Подстановка Line из design/contract.md."""

    n: int | None = None
    t: float | str | None = None
    who: str | None = None
    text: str = ""
    s: float | None = None
    seg: str | None = None


class Dialog(BaseModel):
    """Подстановка Dialog из design/contract.md."""

    id: str
    ch: str = "chat"
    lines: list[Line] | None = None


def anonymized(text: str) -> str:
    """Текст единственной реплики клиента после обезличивания."""
    dialog = Dialog(id="d-1", lines=[Line(n=1, t="00:01", who="client", text=text)])
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
