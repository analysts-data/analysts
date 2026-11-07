"""Разбор снимка организаторов: метки времени и конверт набора.

Чистое ядро без ввода-вывода; нормализация в `Dialog` дорастёт здесь же в группе 2.
"""

import re
from datetime import UTC, datetime

_MMSS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
_EXCESS_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


def ts_seconds(ts: str) -> float | None:
    """Секунды из метки источника.

    `MM:SS` и `H:MM:SS` — секунды от нуля, ISO 8601 — секунды POSIX.
    Дробная часть длиннее шести знаков обрезается, строка без пояса считается UTC.
    Неразобранная метка даёт `None`.
    """
    text = ts.strip()
    match = _MMSS_RE.fullmatch(text)
    if match:
        hours, minutes, seconds = match.groups()
        if int(seconds) > 59 or (hours is not None and int(minutes) > 59):
            return None
        total = (int(hours) * 3600 if hours is not None else 0) + int(minutes) * 60 + int(seconds)
        return float(total)
    try:
        moment = datetime.fromisoformat(_EXCESS_FRACTION_RE.sub(r"\1", text))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()
