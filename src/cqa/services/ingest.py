"""Источник диалогов организаторов: реализует `DialogSource` из `cqa.services.ports`."""

import logging
import os
from collections.abc import Callable
from datetime import datetime

from cqa.adapters.org_api import OrgApi, OrgApiError
from cqa.domain.ingest import OrgPayload, PayloadError, ingest_records, parse_payload
from cqa.domain.models import IngestResult
from cqa.services.errors import Invalid, Upstream
from cqa.settings import Settings

log = logging.getLogger("cqa.ingest")


class OrgDialogSource:
    def __init__(
        self, settings: Settings, api: OrgApi, *, now: Callable[[], datetime] = datetime.now
    ) -> None:
        self._settings = settings
        self._api = api
        self._now = now

    async def fetch(self, group_id: str) -> IngestResult:
        """Один GET, разбор конверта, атомарный снимок `<raw_dir>/<group_id>.json`, журнал."""
        try:
            body = await self._api.fetch_group(group_id)
        except ValueError as exc:  # group_url: недопустимый group_id, запроса не было
            raise Invalid(str(exc)) from None
        except OrgApiError as exc:
            raise Upstream(f"набор {group_id}: {exc}") from None
        try:
            payload = parse_payload(body)
        except PayloadError as exc:
            raise Upstream(f"набор {group_id}: {exc}") from None
        path = self._settings.raw_dir / f"{group_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)
        return self._ingest(payload, group_id)

    def upload(self, raw: bytes) -> IngestResult:
        """Файл того же формата: разбор и журнал, без снимка."""
        try:
            payload = parse_payload(raw)
        except PayloadError as exc:
            raise Invalid(f"файл не в формате организаторов: {exc}") from None
        return self._ingest(payload, payload.group_id)

    async def audio_link(self, audio_url: str) -> str | None:
        # ponytail: OrgApi.fresh_audio_link приходит с группой 5 (feat/dialog-ingest-audio), тогда
        # здесь будет `return await self._api.fresh_audio_link(audio_url)`.
        raise NotImplementedError("OrgApi.fresh_audio_link ещё не в main")

    def _ingest(self, payload: OrgPayload, group_id: str) -> IngestResult:
        settings = self._settings
        result, warnings = ingest_records(
            payload.records,
            group_id=group_id,
            now=self._now(),
            shift_s=settings.audio_shift_s,
            shift_paused_s=settings.audio_shift_paused_s,
        )
        for line in [*(f"{group_id}: {w}" for w in payload.warnings), *warnings, *result.errors]:
            log.warning("%s", line)
        return result
