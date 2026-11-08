"""Вставка диалога текстом: роли, продолжение реплик, язык, id `paste-<n>` и сегменты как у чата."""

from datetime import datetime

import pytest

from cqa.domain.models import Fold, Line
from cqa.domain.paste import PasteError, detect_lang, paste_dialog

NOW = datetime(2026, 11, 8, 12, 0)

RU = (
    "Клиент: Здравствуйте, хочу подать заявку на карту.\n"
    "Оператор: Добрый день! Как вас зовут?\n"
    "Клиент: Меня зовут Анна"
)
KZ = "Клиент: Сәлеметсіз бе, мен карта ашқым келеді\nОператор: Жарайды, атыңыз кім?"
EN = "Customer: Hello, I cannot log in\nOperator: Sure, let me help you"


def paste(text: str, **kwargs: object) -> object:
    kwargs.setdefault("title", "Новый диалог")
    kwargs.setdefault("ch", "chat")
    kwargs.setdefault("taken", ())
    return paste_dialog(text=text, now=NOW, **kwargs)


def lines(dialog: object) -> list[Line]:
    assert dialog.lines is not None
    return [line for line in dialog.lines if isinstance(line, Line)]


def test_roles_case_and_spaces_around_colon_do_not_matter() -> None:
    dialog = paste("  кЛИЕНТ : привет\nоператор\t:  здравствуйте")
    assert [line.who for line in lines(dialog)] == ["client", "operator"]
    assert [line.n for line in lines(dialog)] == [1, 2]
    assert lines(dialog)[0].text == "привет"
    assert (dialog.id, dialog.ch, dialog.lang) == ("paste-1", "chat", "RU")
    assert dialog.title == "Новый диалог"
    assert dialog.at == NOW.strftime("%d.%m %H:%M")


def test_line_without_role_continues_previous_and_empty_lines_are_skipped() -> None:
    dialog = paste("Клиент: привет\n\nещё вопрос по карте\n\nОператор: отвечаю")
    assert [line.who for line in lines(dialog)] == ["client", "operator"]
    assert lines(dialog)[0].text == "привет\nещё вопрос по карте"


def test_kz_and_en_examples_get_language_and_aliases() -> None:
    assert detect_lang(RU) == "RU"
    assert paste(KZ).lang == "KZ"
    en = paste(EN)
    assert (en.lang, [line.who for line in lines(en)]) == ("EN", ["client", "operator"])
    bot = paste("Бот: Здравствуйте! Я помощник\nСистема: Bot dialog started\nOperator: hello")
    assert [line.who for line in lines(bot)] == ["bot", "system", "operator"]


def test_segments_and_folds_are_like_an_ingested_chat() -> None:
    text = (
        "Клиент: Алло, вы здесь?\n"
        "Оператор: Да, слушаю\n"
        "Система: Клиент находится на удержании\n"
        "Система: Клиент больше не находится на удержании\n"
        "Клиент: Спасибо, что ждали"
    )
    dialog = paste(text)
    assert [line.seg for line in lines(dialog)] == ["pre", "conv", "internal", "internal", "conv"]
    assert [line.t for line in lines(dialog)] == ["00:00", "00:01", "00:02", "00:03", "00:04"]
    assert any(isinstance(line, Fold) for line in dialog.lines or [])


def test_missing_operator_or_role_in_first_line_or_no_turns_is_an_error() -> None:
    with pytest.raises(PasteError, match="оператора"):
        paste("Клиент: один на свете")
    with pytest.raises(PasteError, match="роли"):
        paste("просто текст без роли\nОператор: поздно")
    with pytest.raises(PasteError, match="реплик"):
        paste("  \n\n")


def test_id_is_the_first_paste_n_not_taken() -> None:
    assert paste(RU, taken={"call-024", "paste-1"}).id == "paste-2"
    assert paste(RU, taken={"paste-1", "paste-3"}).id == "paste-2"


def test_call_channel_and_empty_title_fall_back_to_ingest_defaults() -> None:
    dialog = paste(RU, ch="call", title="  ")
    assert (dialog.ch, dialog.title) == ("call", "Звонок paste-1")
