"""Сбор и сводка метрик использования (POST /api/telemetry, GET /api/usage)."""

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any, Literal

from cqa.adapters.store import Store
from cqa.domain.review import ASTANA
from cqa.domain.usage import UsageEvent, aggregate, clean_props, to_csv

UsageFormat = Literal["json", "csv"]


class TokenBucket:
    """Лимит запросов на клиента: capacity подряд, затем rate в секунду."""

    # ponytail: память одного процесса без вытеснения клиентов; хватает для одного сервера в отделе
    def __init__(self, capacity: float, rate: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity, self._rate, self._clock = capacity, rate, clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def take(self, client: str) -> bool:
        now = self._clock()
        tokens, last = self._buckets.get(client, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._rate)
        ok = tokens >= 1
        self._buckets[client] = (tokens - ok, now)
        return ok


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds")


def record(
    store: Store, events: Sequence[tuple[datetime, str, str, dict[str, Any]]], actor: str, role: str | None
) -> None:
    """events — (at, event, page, props); props очищаются от текста до записи."""
    store.add_telemetry(
        [
            (_iso(at), actor, role, event, page, json.dumps(clean_props(props)))
            for at, event, page, props in events
        ]
    )


def purge(store: Store, days: int, now: datetime) -> None:
    store.purge_telemetry(_iso(now - timedelta(days=days)))


def usage(store: Store, fmt: UsageFormat, *, since: date | None, role: str | None) -> dict[str, Any] | str:
    after = _iso(datetime.combine(since, dtime(), ASTANA)) if since else None
    events = [
        UsageEvent(datetime.fromisoformat(at), actor, r, event, page, json.loads(props))
        for at, actor, r, event, page, props in store.telemetry(after, role)
    ]
    body = {"filters": {"since": since.isoformat() if since else None, "role": role}, **aggregate(events)}
    return body if fmt == "json" else to_csv(body)
