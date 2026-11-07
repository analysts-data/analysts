"""Разбор снимка организаторов: метки времени, конверт набора и сегменты реплик.

Чистое ядро без ввода-вывода; нормализация в `Dialog` дорастёт здесь же в группе 2.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from cqa.domain.events import EventKind

_MMSS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
_EXCESS_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


class OrgTurn(BaseModel):
    """Реплика транскрипта организаторов; лишние поля игнорируются."""

    timestamp: str
    speaker: str
    text: str


class OrgRecord(BaseModel):
    """Запись диалога организаторов; лишние поля игнорируются."""

    conversation_id: str
    channel: str
    language: str
    transcript: list[OrgTurn]
    audio_url: str | None = None


class PayloadError(ValueError):
    """Тело не конверт организаторов: не JSON, `isSuccess` не true, нет `data.records`."""


@dataclass(frozen=True)
class OrgPayload:
    """Разобранный конверт; необработанные записи проверяются по одной позже."""

    group_id: str
    records: list[dict[str, Any]]
    warnings: list[str]


def parse_payload(body: bytes) -> OrgPayload:
    """Разбирает конверт `{error, isSuccess, data: {dataset_group_id, total_records, records}}`."""
    try:
        envelope: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayloadError(f"тело не JSON: {exc}") from None
    if not isinstance(envelope, dict):
        raise PayloadError("конверт организаторов должен быть JSON-объектом")
    if envelope.get("isSuccess") is not True:
        error = envelope.get("error")
        detail = f": {error}" if isinstance(error, str) and error else ""
        raise PayloadError(f"организаторы ответили ошибкой{detail}")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise PayloadError("в конверте нет объекта data")
    records = data.get("records")
    if not isinstance(records, list):
        raise PayloadError("data.records должен быть списком")
    warnings: list[str] = []
    total = data.get("total_records")
    if isinstance(total, int) and not isinstance(total, bool) and total != len(records):
        warnings.append(f"total_records {total} не совпадает с числом записей {len(records)}")
    group_id = data.get("dataset_group_id")
    return OrgPayload(
        group_id=group_id if isinstance(group_id, str) else "",
        records=list(records),
        warnings=warnings,
    )


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


Who = Literal["client", "operator", "bot", "system"]
Seg = Literal["pre", "conv", "internal", "after"]


def segments(who: Sequence[Who], kinds: Sequence[EventKind | None]) -> tuple[list[Seg], list[str]]:
    """Сегменты по порядку источника: `after` → `pre` → `internal` → `conv`; и предупреждения.

    Окно `internal` открыто, пока стоит флаг удержания или консультации; граничные события в окне.
    Первое `end` закрывает незакрытое окно и само остаётся `conv`.
    """
    if "operator" not in who:
        return ["pre"] * len(who), ["нет реплик оператора, все реплики pre"]
    first_op = list(who).index("operator")
    end = next((i for i, k in enumerate(kinds) if k == "end"), len(kinds))
    hold = consult = False
    segs: list[Seg] = []
    warnings: list[str] = []
    for i, k in enumerate(kinds):
        was_open = hold or consult
        if i == end and was_open:
            warnings.append(f"окно удержания или консультации не закрыто до реплики {i + 1}")
        if k == "hold_start":
            hold = True
        elif k == "hold_end":
            hold = False
        elif k == "consult_start":
            consult = True
        elif k == "consult_end":
            consult = False
        if i > end:
            segs.append("after")
        elif i < first_op:
            segs.append("pre")
        elif i < end and (was_open or hold or consult):
            segs.append("internal")
        else:
            segs.append("conv")
    if end == len(kinds) and (hold or consult):
        warnings.append("окно удержания или консультации не закрыто до конца диалога")
    return segs, warnings
