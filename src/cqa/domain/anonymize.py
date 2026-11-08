"""Локальное обезличивание диалога до отправки любой модели (design.md п. 18).

Шаблоны персональных данных применяются только вне квадратных скобок, поэтому
маски организаторов не меняются. Порядок замен: почта, IBAN, карта, ИИН,
телефон. Номера, роли, сегменты и время реплик не меняются, меняется только
текст реплик; входной диалог остаётся как есть.

Имена ищутся по подсказкам на RU, KZ и EN и в коротком ответе клиента на
вопрос оператора, метка роли — по `who` реплики с именем. Найденное имя
заменяется во всём диалоге без учёта регистра вместе с близкими вариантами
распознавания речи (difflib, порог 0.8, слово от 4 букв).
# ponytail: подсказки и difflib вместо NER, NER при росте пропусков на замере.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher

from cqa.domain.models import Dialog, Fold, Line


def _luhn(number: str) -> bool:
    """Проверка Луна: сумма с удвоением каждой второй цифры справа кратна 10."""
    total = 0
    for index, digit in enumerate(reversed(number)):
        value = int(digit)
        if index % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _card_if_luhn(match: re.Match[str]) -> str:
    """Карта без разделителей — только по Луну; номер заявки без Луна остаётся как есть."""
    return "[НОМЕР_КАРТЫ]" if _luhn(match.group(0)) else match.group(0)


def _phone_after_word(match: re.Match[str]) -> str:
    """Телефон без + и 8 маскируется, слово-подсказка перед ним сохраняется."""
    return f"{match.group(1)}[ТЕЛЕФОН]"


# Порядок шаблонов — design.md п. 18: почта, IBAN KZ, карта 16 цифр, ИИН 12 цифр, телефон.
# Дополнения идут после базовых: карта без разделителей по Луну, ИИН с пробелами (6+6 и
# 4+4+4), телефон KZ без + и 8 — только после слова-подсказки в пределах 20 символов.
_PATTERNS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[ПОЧТА]"),
    (re.compile(r"(?<![A-Z0-9])KZ\d{2}[A-Z0-9]{16}(?![A-Z0-9])"), "[НОМЕР_СЧЁТА]"),
    (re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){3}(?!\d)"), "[НОМЕР_КАРТЫ]"),
    (re.compile(r"(?<!\d)\d{13,19}(?!\d)"), _card_if_luhn),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[ДАННЫЕ_ИДЕНТИФИКАЦИИ]"),
    (re.compile(r"(?<!\d)\d{6} \d{6}(?!\d)"), "[ДАННЫЕ_ИДЕНТИФИКАЦИИ]"),
    (re.compile(r"(?<!\d)\d{4} \d{4} \d{4}(?!\d)"), "[ДАННЫЕ_ИДЕНТИФИКАЦИИ]"),
    (re.compile(r"(?<!\d)(?:\+7|8)(?:[\s() -]*\d){10}(?!\d)"), "[ТЕЛЕФОН]"),
    (
        re.compile(
            r"((?:телефон|номер|тел|звоните)\b\D{0,20})7 \d{3} \d{3} \d{2} \d{2}(?!\d)", re.IGNORECASE
        ),
        _phone_after_word,
    ),
)

# Участки в квадратных скобках (маски организаторов) не перекрашиваем.
_OUTSIDE_BRACKETS = re.compile(r"[^\[\]]+")

# Буквы RU, KZ и EN для захвата имён и токенов.
_WORD = r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІіЇїЎўЄєҐґA-Za-z]+"
_WORD_RE = re.compile(_WORD)

# Подсказки перед именем; длинные раньше коротких («менің атым» раньше «атым»).
_HINTS = "менің атым|меня зовут|моё имя|мое имя|есімім|атым|my name is"
_HINT_RE = re.compile(rf"(?<!\w)(?:{_HINTS})\s+({_WORD})(?:\s+({_WORD}))?", re.IGNORECASE)

# Представление без подсказки: «я Марк», «I'm Adrian», «мен Мұратпын» (личное окончание отбрасывается).
# Имя — слово с заглавной буквы; только реплики оператора и клиента (бот представляет себя сам).
_KZ_SUFFIX = "мын|мін|пын|пін|бын|бін"
_UPPER = "А-ЯЁӘҒҚҢӨҰҮҺІA-Z"
_LOWER = "а-яёәғқңөұүһіa-z"
_SELF_RE = re.compile(
    rf"(?<!\w)(?:[Яя]|I'm|I am|[Мм]ен)\s+([{_UPPER}][{_LOWER}]+?)(?:{_KZ_SUFFIX})?(?![{_UPPER}{_LOWER}])"
)
_PEOPLE = frozenset({"operator", "client"})

# Вопрос оператора об имени клиента.
_QUESTION_RE = re.compile(
    r"(?<!\w)(?:как к вам обращаться|как вас зовут|атыңыз кім|сізге қалай жүгінуге болады"
    r"|how should i address you|what is your name)",
    re.IGNORECASE,
)

# Служебные слова и названия, которые не могут быть именем (design.md п. 18).
_STOP = frozenset(
    {
        "а",
        "но",
        "если",
        "уже",
        "ещё",
        "еще",
        "там",
        "тут",
        "так",
        "тоже",
        "очень",
        "просто",
        "и",
        "в",
        "во",
        "не",
        "ни",
        "на",
        "по",
        "до",
        "из",
        "за",
        "к",
        "с",
        "со",
        "о",
        "об",
        "я",
        "мы",
        "вы",
        "ты",
        "он",
        "она",
        "оно",
        "они",
        "меня",
        "зовут",
        "моё",
        "мое",
        "имя",
        "мой",
        "моя",
        "ваш",
        "ваша",
        "вас",
        "вам",
        "вами",
        "сіз",
        "сізге",
        "сізді",
        "сізбен",
        "sorry",
        "да",
        "нет",
        "как",
        "что",
        "чтобы",
        "пожалуйста",
        "спасибо",
        "здравствуйте",
        "добрый",
        "день",
        "вечер",
        "привет",
        "брокер",
        "фридом",
        "freedom",
        "і",
        "мен",
        "менің",
        "атым",
        "есімім",
        "және",
        "i",
        "me",
        "my",
        "am",
        "is",
        "are",
        "name",
        "and",
        "the",
        "a",
        "an",
        "to",
        "from",
        "hello",
        "hi",
        "please",
        "thanks",
        "thank",
        "you",
    }
)

_MAX_ANSWER_WORDS = 4
_FUZZY_MIN_LEN = 4
_FUZZY_RATIO = 0.8


def _apply_patterns(text: str) -> str:
    """Заменяет шаблоны только в участках вне квадратных скобок."""

    def substitute(match: re.Match[str]) -> str:
        segment = match.group(0)
        for pattern, label in _PATTERNS:
            segment = pattern.sub(label, segment)
        return segment

    return _OUTSIDE_BRACKETS.sub(substitute, text)


def _hint_name(first: str, second: str | None) -> str | None:
    """Имя из слов после подсказки: до двух слов, второе не служебное."""
    if first.casefold() in _STOP:
        return None
    if second and second.casefold() not in _STOP:
        return f"{first} {second}"
    return first


def _answer_name(text: str) -> str | None:
    """Первое неслужебное слово короткой реплики клиента."""
    words = text.split()
    if len(words) > _MAX_ANSWER_WORDS:
        return None
    for word in words:
        found = _WORD_RE.search(word)
        if found and found.group(0).casefold() not in _STOP:
            return found.group(0)
    return None


def _discover_names(lines: list[Line | Fold]) -> list[tuple[str, str]]:
    """Пары (имя, метка роли) в порядке появления; метка — по who реплики с именем."""
    candidates: list[tuple[int, int, str, str]] = []  # индекс реплики, позиция, имя, who
    for index, line in enumerate(lines):
        if isinstance(line, Fold) or not line.text:
            continue
        who = line.who
        for match in _HINT_RE.finditer(line.text):
            name = _hint_name(match.group(1), match.group(2))
            if name:
                candidates.append((index, match.start(1), name, who))
        if who in _PEOPLE:
            for match in _SELF_RE.finditer(line.text):
                if match.group(1).casefold() not in _STOP:
                    candidates.append((index, match.start(1), match.group(1), who))
        if who == "operator" and _QUESTION_RE.search(line.text):
            for later_index in range(index + 1, len(lines)):
                later = lines[later_index]
                if isinstance(later, Fold):
                    continue
                if later.who == "client" and later.text:
                    name = _answer_name(later.text)
                    if name:
                        candidates.append((later_index, 0, name, "client"))
                    break

    labels: dict[str, str] = {}
    clients = 0
    for _, _, name, name_who in sorted(candidates, key=lambda c: (c[0], c[1])):
        key = re.sub(r"\s+", " ", name).casefold()
        if key in labels:
            continue
        if name_who == "operator":
            labels[key] = "[ИМЯ_ОПЕРАТОРА]"
        else:
            clients += 1
            labels[key] = f"[ИМЯ_КЛИЕНТА_{clients}]"
    # Сначала длинные имена, чтобы «иван петров» не разлетелся на два ярлыка.
    return sorted(labels.items(), key=lambda item: -len(item[0].split()))


def _replace_names(text: str, names: list[tuple[str, str]]) -> str:
    """Точное вхождение имени и близкие варианты распознавания — в метку роли."""
    for name, label in names:
        words = r"\s+".join(re.escape(w) for w in name.split())
        pattern = rf"(?<!\w){words}(?:{_KZ_SUFFIX})?(?!\w)"
        text = re.sub(pattern, label, text, flags=re.IGNORECASE)
    pieces: list[str] = []
    last_end = 0
    for match in _WORD_RE.finditer(text):
        token = match.group(0)
        if len(token) < _FUZZY_MIN_LEN:
            continue
        for name, label in names:
            for word in name.split():
                ratio = SequenceMatcher(None, token.casefold(), word.casefold()).ratio()
                if len(word) >= _FUZZY_MIN_LEN and ratio >= _FUZZY_RATIO:
                    pieces.append(text[last_end : match.start()])
                    pieces.append(label)
                    last_end = match.end()
                    break
            else:
                continue
            break
    pieces.append(text[last_end:])
    return "".join(pieces)


def anonymize(dialog: Dialog) -> Dialog:
    """Новый диалог с обезличенным текстом реплик; вход не меняется."""
    if dialog.lines is None:
        return dialog.model_copy()
    names = _discover_names(dialog.lines)
    new_lines = [
        line.model_copy(update={"text": _apply_patterns(_replace_names(line.text, names))})
        if isinstance(line, Line)
        else line
        for line in dialog.lines
    ]
    return dialog.model_copy(update={"lines": new_lines})
