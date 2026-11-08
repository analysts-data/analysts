"""Вставка диалога текстом (`POST /api/dialogs/text`): строки «Роль: текст» → `Dialog`.

Сборка реплик, сегментов и свёрток переиспользует `build_dialog` загрузки чатов,
поэтому вставленный диалог неотличим от диалога из API организаторов. Чистая функция.
"""

import re
from collections.abc import Collection
from datetime import datetime
from typing import Literal

from cqa.domain.ingest import OrgRecord, OrgTurn, build_dialog
from cqa.domain.models import Dialog

# Роли по контракту: клиент, оператор, бот, событие; регистр и пробелы не важны.
ROLES: dict[str, str] = {
    "клиент": "client",
    "client": "client",
    "customer": "client",
    "оператор": "operator",
    "operator": "operator",
    "менеджер": "operator",
    "бот": "bot",
    "bot": "bot",
    "система": "system",
    "system": "system",
}
_LINE_RE = re.compile(r"^([^:]+?)\s*:\s*(.*)$")

# Буквы, отличающие казахский текст от русского и латиницы; язык диалога — по тексту.
_KZ_LETTERS = "әғқңөұүһі"
_CYR_LETTERS = "абвгдежзийклмнопрстуфхцчшщъыьэюяё"


class PasteError(ValueError):
    """Текст не разбирается в диалог: нет реплик, роли в первой строке или реплики оператора."""


def detect_lang(text: str) -> Literal["RU", "KZ", "EN"]:
    """`KZ`, если есть казахские буквы; иначе `RU` по кириллице; иначе `EN`."""
    lower = text.casefold()
    if any(ch in lower for ch in _KZ_LETTERS):
        return "KZ"
    if any(ch in lower for ch in _CYR_LETTERS):
        return "RU"
    return "EN"


def _turns(text: str) -> list[OrgTurn]:
    turns: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        who: str | None = None
        body = line
        if match is not None:
            found = ROLES.get(match.group(1).casefold())
            if found is not None:
                who, body = found, match.group(2).strip()
        if who is None:
            if not turns:
                raise PasteError(f"в первой строке нет роли «Клиент:», «Оператор:» и т.п.: {line[:50]!r}")
            turns[-1] = (turns[-1][0], f"{turns[-1][1]}\n{line}")
        else:
            turns.append((who, body))
    if not turns:
        raise PasteError("в тексте нет реплик")
    if not any(who == "operator" for who, _ in turns):
        raise PasteError("в диалоге нет реплики оператора")
    # Метки «MM:SS» по минуте на реплику: у вставки нет времени источника.
    return [
        OrgTurn(timestamp=f"{i // 60:02d}:{i % 60:02d}", speaker=who, text=body)
        for i, (who, body) in enumerate(turns)
    ]


def paste_dialog(
    *, title: str, ch: Literal["chat", "call"], text: str, taken: Collection[str], now: datetime
) -> Dialog:
    """Текст → `Dialog`: строка без роли продолжает предыдущую реплику, `n` с 1, `id` — `paste-<n>`.

    `id` — первый свободный `paste-<n>` среди уже сохранённых `taken`, без коллизий.
    Пустое название заменяется заголовком как у загруженных диалогов.
    """
    turns = _turns(text)
    dialog_id = next(f"paste-{n}" for n in range(1, len(taken) + 2) if f"paste-{n}" not in taken)
    record = OrgRecord(
        conversation_id=dialog_id,
        channel="agent chat" if ch == "chat" else "voice call",
        language=detect_lang(text).lower(),
        transcript=turns,
    )
    dialog, _warnings = build_dialog(record, now=now, shift_s=0.0, shift_paused_s=0.0)
    title = title.strip()
    return dialog if not title else dialog.model_copy(update={"title": title})
