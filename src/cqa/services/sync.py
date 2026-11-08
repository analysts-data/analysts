"""Синхронизация источников, которые сервер забирает сам (`org_api`, `http_json`): кнопкой и по расписанию.

Каждый проход — строка журнала `source_syncs` (`running`, затем `ok`, `partial` или `error`); ошибка
прохода не останавливает цикл. `PUT /api/source` — прежний путь: ссылка API организаторов → источник `org`.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cqa.adapters.http_source import HttpSource, SourceFetchError
from cqa.adapters.store import Store
from cqa.domain.models import IngestResult
from cqa.domain.sources import PULL, org_url_error
from cqa.services.datasets import logged
from cqa.services.errors import Conflict, Invalid, NotFound, Unavailable
from cqa.services.ports import DialogSource
from cqa.services.sources import build, check, extract, failed, preview
from cqa.settings import Settings

TICK_S = 30.0  # как часто цикл смотрит, кому пора; расписание источника — schedule_min
log = logging.getLogger("cqa.sync")


def _now() -> datetime:
    return datetime.now(UTC)


class Syncer:
    def __init__(
        self,
        store: Store,
        source: DialogSource,
        http: HttpSource | None = None,
        settings: Settings | None = None,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._store = store
        self._source = source
        self.http = http  # http_json; None — такие источники не синхронизируются (503)
        self._settings = settings or Settings(_env_file=None)  # type: ignore[call-arg]
        self._clock = clock

    async def _records(self, src: dict[str, Any]) -> tuple[list[Any], IngestResult, list[dict[str, Any]]]:
        """Один запрос к источнику: сырые записи, диалоги и сопоставленные записи (для предпросмотра)."""
        if src["kind"] == "org_api":
            if not src["secret"]:
                raise Invalid("Нет ссылки API организаторов")
            result = await self._source.fetch(str(src["config"].get("group_id", "")), src["secret"])
            return result.dialogs, result, []
        if self.http is None:
            raise Unavailable("Запросы к внешним источникам не подключены")
        cfg = src["config"]
        headers = {cfg["auth_header"]: src["secret"]} if cfg.get("auth_header") and src["secret"] else {}
        raw = await self.http.fetch(cfg["url"], method=cfg.get("method", "GET"), headers=headers)
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise Invalid("Ответ источника не JSON") from None
        records = extract(src, body)
        result, mapped = build(src, records, self._settings, self._clock())
        return records, result, mapped

    async def sync_source(self, source_id: str) -> dict[str, Any]:
        """Забрать сейчас; ответ — строка журнала. Ошибка источника — `status: "error"`, а не исключение."""
        src = self._store.source(source_id)
        if src is None:
            raise NotFound(f"Источник {source_id} не найден")
        if src["kind"] not in PULL:
            raise Invalid("Этот источник сам присылает данные: синхронизировать нечего")
        last = self._store.syncs(source_id, 1)
        if last and last[0]["status"] == "running":
            raise Conflict("Синхронизация уже идёт")
        try:
            with logged(self._store, source_id) as save:
                save((await self._records(src))[1])
        except Exception as exc:  # уже в журнале; цикл и ответ не падают
            log.warning("синхронизация %s: %s", source_id, exc)
        return self._store.syncs(source_id, 1)[0]

    async def test(self, src: dict[str, Any], sample: Any = None) -> dict[str, Any]:
        """Связь и предпросмотр первых 3 записей без сохранения; сбой — `ok: false` с текстом."""
        t0 = time.monotonic()

        def ms() -> int:
            return round((time.monotonic() - t0) * 1000)

        try:
            if src["kind"] == "webhook":
                if sample is None:
                    raise Invalid("Проверьте поля источника", {"sample": "вставьте пример тела запроса"})
                records = extract(src, sample)
                result, mapped = build(src, records, self._settings, self._clock())
            elif src["kind"] in PULL:
                records, result, mapped = await self._records(src)
            else:
                raise Invalid("У встроенного источника нечего проверять")
        except (SourceFetchError, Unavailable) as exc:
            return failed(str(exc), ms())
        except Invalid as exc:
            if exc.fields:
                raise
            return failed(str(exc), ms())
        except Exception as exc:  # Upstream организаторов и прочее — текст без адреса
            return failed(str(exc), ms())
        return preview(records, result, mapped, ms=ms())

    async def test_draft(self, body: dict[str, Any], sample: Any = None) -> dict[str, Any]:
        """Проверка из мастера до сохранения: те же поля, что у `POST /api/sources`."""
        check({**body, "enabled": False}, saved_secret=None)
        src = {
            **body,
            "id": "new",
            "config": dict(body.get("config") or {}),
            "secret": (body.get("secret") or "").strip() or None,
        }
        return await self.test(src, sample)

    async def configure(self, url: str, group_id: str) -> dict[str, int]:
        """`PUT /api/source`: сразу забирает набор по новой ссылке, сохраняет её после удачной загрузки."""
        url, group_id = url.strip(), group_id.strip()
        if msg := org_url_error(url):
            raise Invalid(msg)
        if not group_id:
            raise Invalid("Укажите group_id")
        with logged(self._store, "org") as save:
            counts = save(await self._source.fetch(group_id, url))
        self._store.set_org_source(url, group_id)
        return counts

    def _due(self, src: dict[str, Any], now: datetime) -> bool:
        last = self._store.syncs(src["id"], 1)
        if not last:
            return True
        if last[0]["status"] == "running":
            return False
        return now >= datetime.fromisoformat(last[0]["started"]) + timedelta(minutes=src["schedule_min"])

    async def sync(self) -> None:
        """Один проход цикла: включённые источники с расписанием, которым пора."""
        now = self._clock()
        for src in self._store.sources():
            on = src["enabled"] and not src["archived"] and src["schedule_min"] > 0
            if src["kind"] in PULL and on and self._due(src, now):
                await self.sync_source(src["id"])

    def status(self) -> dict[str, Any] | None:
        """`{group_id, synced_at, added, skipped, error}` источника `org` для `GET /api/state`."""
        saved = self._store.org_source()
        if saved is None:
            return None
        done = [s for s in self._store.syncs("org", 5) if s["status"] != "running"]
        if not done:
            return {"group_id": saved[1]}
        last = done[0]
        error = last["errors"][0] if last["status"] == "error" and last["errors"] else None
        return {
            "group_id": saved[1],
            "synced_at": last["finished"],
            "added": last["added"],
            "skipped": last["skipped"],
            "error": error,
        }

    async def run(self, interval_s: float = TICK_S) -> None:
        while True:
            await self.sync()
            await asyncio.sleep(interval_s)
