"""Ответ организаторов → `Dialog`: метки времени, конверт, события, сегменты, свёртки.

Чистое ядро без ввода-вывода.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from typing import Any, Literal, get_args

from pydantic import BaseModel, ValidationError

from cqa.domain.events import EventKind, classify_event, normalize
from cqa.domain.models import Dialog, Fold, IngestResult, Line

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


_WHO: dict[str, Who] = {w: w for w in get_args(Who)}
_CHANNELS: dict[str, Literal["chat", "call"]] = {"agent chat": "chat", "voice call": "call"}
_FOLD_LABELS: dict[str, str] = {
    "internal": "Удержание и разговор с коллегой",
    "after": "После конца разговора",
}
_AT = "%d.%m %H:%M"


def build_dialog(
    record: OrgRecord, *, now: datetime, shift_s: float, shift_paused_s: float
) -> tuple[Dialog, list[str]]:
    """Запись организаторов → `Dialog` по `design/contract.md` и предупреждения без `conversation_id`."""
    warnings: list[str] = []
    ch = _CHANNELS.get(record.channel)
    if ch is None:
        ch = "call" if record.audio_url else "chat"
        warnings.append(f"неизвестный канал {record.channel!r}, взят {ch}")
    turns = record.transcript

    who: list[Who] = []
    for n, turn in enumerate(turns, 1):
        role = _WHO.get(turn.speaker)
        if role is None:
            warnings.append(f"реплика {n}: неизвестный speaker {turn.speaker!r}, взят system")
            role = "system"
        who.append(role)

    parsed = [ts_seconds(turn.timestamp) for turn in turns]
    secs: list[float] = []
    last = next((x for x in parsed if x is not None), 0.0)
    for n, (turn, x) in enumerate(zip(turns, parsed, strict=True), 1):
        if x is None:
            warnings.append(f"реплика {n}: метка {turn.timestamp!r} не разобрана, взято время предыдущей")
        last = last if x is None else x
        secs.append(last)

    kinds = [
        classify_event(t.text) if w in ("system", "bot") else None for w, t in zip(who, turns, strict=True)
    ]
    for n, (w, k, turn) in enumerate(zip(who, kinds, turns, strict=True), 1):
        if w == "system" and k is None:
            warnings.append(f"реплика {n}: неизвестное событие {turn.text!r}")

    segs, seg_warnings = segments(who, kinds)
    warnings += seg_warnings
    norms = [normalize(turn.text) for turn in turns]
    dup = [i > 0 and who[i] == who[i - 1] and norms[i] == norms[i - 1] for i in range(len(turns))]
    warnings += [f"реплика {i + 1} повторяет {i}" for i, d in enumerate(dup) if d]

    starts: list[float | None] = [None] * len(turns)
    t: list[float | str]
    fold_t: Sequence[float | str]
    if ch == "call":
        t = [s if s is not None else round(x - secs[0], 1) for s, x in zip(starts, secs, strict=True)]
        fold_t = t
        dur = round(secs[-1] - secs[0], 1) if secs else None
        at = _call_at(
            next((turn.timestamp for turn, x in zip(turns, parsed, strict=True) if x is not None), None)
        )
    else:
        t = [turn.timestamp for turn in turns]
        fold_t = secs
        dur = None
        at = None
    items: list[Line | Fold] = []
    i = 0
    for seg, group in groupby(segs):
        size = len(list(group))
        if seg in _FOLD_LABELS:
            label = _FOLD_LABELS[seg]
            items.append(
                Fold(fold=True, from_=i + 1, to=i + size, t0=fold_t[i], t1=fold_t[i + size - 1], label=label)
            )
        for j in range(i, i + size):
            turn = turns[j]
            fields: dict[str, Any] = {
                "n": j + 1,
                "t": t[j],
                "ts": turn.timestamp,
                "who": who[j],
                "text": turn.text,
                "s": starts[j],
                "seg": seg,
            }
            if dup[j]:
                fields["dup"] = True
            items.append(Line.model_validate(fields))
        i += size

    title = ("Звонок " if ch == "call" else "Чат ") + record.conversation_id
    dialog = Dialog(
        id=record.conversation_id,
        title=title,
        ch=ch,
        lang=record.language.upper(),
        dur=dur,
        at=at or now.strftime(_AT),
        lines=items,
    )
    return dialog, warnings


def _call_at(ts: str | None) -> str | None:
    """`ДД.ММ ЧЧ:ММ` первой метки ISO в её поясе; `None`, если это не ISO."""
    try:
        return datetime.fromisoformat((ts or "")[:16]).strftime(_AT)
    except ValueError:
        return None


def ingest_records(
    records: Sequence[Mapping[str, Any]],
    *,
    group_id: str,
    now: datetime,
    shift_s: float,
    shift_paused_s: float,
) -> tuple[IngestResult, list[str]]:
    """Записи конверта → `IngestResult` и предупреждения `<conversation_id>: <что случилось>`.

    Битая запись идёт в `errors`, повтор `conversation_id` заменяет прежний диалог.
    """
    dialogs: dict[str, Dialog] = {}
    audio: dict[str, str] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for raw in records:
        try:
            record = OrgRecord.model_validate(raw)
        except ValidationError as exc:
            cid = raw.get("conversation_id", "?") if isinstance(raw, Mapping) else "?"
            reason = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            errors.append(f"{cid}: {reason}")
            continue
        cid = record.conversation_id
        dialog, notes = build_dialog(record, now=now, shift_s=shift_s, shift_paused_s=shift_paused_s)
        if cid in dialogs:
            notes.append("повтор conversation_id в пакете, взята последняя запись")
        warnings += [f"{cid}: {note}" for note in notes]
        dialogs[cid] = dialog
        if dialog.ch == "call" and record.audio_url:
            audio[cid] = record.audio_url
    return IngestResult(
        dialogs=list(dialogs.values()), audio=audio, skipped=len(errors), errors=errors
    ), warnings
