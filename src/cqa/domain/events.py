"""Словарь системных событий организаторов: фраза → вид события."""

from typing import Final, Literal

EventKind = Literal[
    "end",
    "hold_start",
    "hold_end",
    "consult_start",
    "consult_end",
    "rec_start",
    "rec_pause",
    "rec_resume",
    "info",
]


def normalize(text: str) -> str:
    """casefold, `ё` → `е`, сжатые пробелы, без хвостовой пунктуации."""
    return " ".join(text.casefold().replace("ё", "е").split()).rstrip(".,!?;:… ")


# Строки интерфейса организаторов как есть; ключи нормализуются ниже.
_PHRASES: Final[dict[str, EventKind]] = {
    "Чат передан оператору": "info",
    "Эскалация на оператора": "info",
    "Идентификация пройдена": "info",
    "Чат операторға жіберілді": "info",
    "Chat transferred to an agent": "info",
    "Личность клиента подтверждена": "info",
    "Клиенттің жеке басы расталды": "info",
    "Customer identity verified": "info",
    "Клиент переведен от агента на представителя службы поддержки": "info",
    "Агент присоединился к разговору с клиентом": "info",
    "Bot dialog and transcription languages have been updated": "info",  # хвост с кодами языков
    "Оператор закрыл чат": "end",
    "Оператор чатты жапты": "end",
    "Клиентпен байланыс үзілді": "end",
    "Connection to customer lost": "end",
    "Клиент покинул чат": "end",
    "Клиент завершил разговор": "end",
    "Соединение с клиентом прервано": "end",
    "Agent closed the chat": "end",
    "Клиент находится на удержании": "hold_start",
    "Клиент больше не находится на удержании": "hold_end",
    "Инициирована консультация с агентом": "consult_start",
    "Началась консультация с агентом": "consult_start",  # повтор старта окно не дублирует
    "Агент вышел из разговора": "consult_end",
    "Запись и транскрибирование запущены": "rec_start",
    "Жазу және транскрипция басталды": "rec_start",
    "Запись и транскрибирование приостановлены": "rec_pause",
    "Запись и транскрибирование возобновлены": "rec_resume",
}

EVENTS: Final[dict[str, EventKind]] = {normalize(phrase): kind for phrase, kind in _PHRASES.items()}


def classify_event(text: str) -> EventKind | None:
    """Вид события по самой длинной фразе, с которой начинается текст; `None` — неизвестное."""
    norm = normalize(text)
    phrase = max((p for p in EVENTS if norm.startswith(p)), key=len, default=None)
    return None if phrase is None else EVENTS[phrase]
