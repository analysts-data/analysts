"""Ссылка API организаторов из интерфейса и автосинхронизация набора.

Ссылка подписана: она хранится в базе и не попадает ни в статус, ни в журнал. Статус живёт в памяти процесса.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from cqa.adapters.store import Store
from cqa.services.datasets import load_group
from cqa.services.errors import Invalid
from cqa.services.ports import DialogSource

SYNC_INTERVAL_S = 300.0  # ponytail: fixed 5 min; a Settings field if the operator needs another pace
log = logging.getLogger("cqa.sync")


class Syncer:
    def __init__(self, store: Store, source: DialogSource) -> None:
        self._store = store
        self._source = source
        self._last: dict[str, Any] = {}

    async def configure(self, url: str, group_id: str) -> dict[str, int]:
        """Сразу забирает набор по новой ссылке; ссылка сохраняется только после удачной загрузки."""
        url, group_id = url.strip(), group_id.strip()
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc:
            raise Invalid("Ссылка API организаторов должна начинаться с https://")
        counts = await load_group(self._store, self._source, group_id, url)
        self._store.set_org_source(url, group_id)
        self._remember(counts, None)
        return counts

    async def sync(self) -> None:
        """Один проход: ошибка уходит в статус и журнал, а не наружу, чтобы цикл не останавливался."""
        saved = self._store.org_source()
        if saved is None:
            return
        url, group_id = saved
        try:
            counts = await load_group(self._store, self._source, group_id, url)
        except Exception as exc:  # любая ошибка прохода не должна остановить цикл
            log.warning("автосинхронизация %s: %s", group_id, exc)
            self._remember(None, str(exc))
        else:
            self._remember(counts, None)

    def status(self) -> dict[str, Any] | None:
        """`{group_id, synced_at, added, skipped, error}` для `GET /api/state`; `None`, пока ссылки нет."""
        saved = self._store.org_source()
        return None if saved is None else {"group_id": saved[1], **self._last}

    async def run(
        self, interval_s: float = SYNC_INTERVAL_S, skip: Callable[[], bool] = lambda: False
    ) -> None:
        """skip() — синхронизацию ведёт автоматизация по своему расписанию, этот проход пропускается."""
        while True:
            if not skip():
                await self.sync()
            await asyncio.sleep(interval_s)

    def _remember(self, counts: dict[str, int] | None, error: str | None) -> None:
        self._last = {
            "synced_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "added": counts["added"] if counts else 0,
            "skipped": counts["skipped"] if counts else 0,
            "error": error,
        }
