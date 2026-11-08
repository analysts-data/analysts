"""Интонация звонка по звуку: считается при первом запросе и хранится в базе."""

from typing import Any

from cqa.adapters.store import Store
from cqa.domain.prosody import analyse
from cqa.services.errors import NotFound, Upstream
from cqa.services.ports import DialogSource, Voice


async def dialog_prosody(store: Store, source: DialogSource, voice: Voice, dialog_id: str) -> dict[str, Any]:
    """404 — чат, неизвестный id или звонок без записи; 502 — запись не получена, в базу не пишется."""
    dialog, audio_url = store.get_dialog(dialog_id), store.audio_url(dialog_id)
    if dialog is None or dialog.ch != "call" or audio_url is None:
        raise NotFound(f"У диалога {dialog_id} нет записи")
    cached = store.prosody(dialog_id)
    if cached is not None:
        return cached
    link = await source.audio_link(audio_url)
    tracks = await voice.tracks(link) if link else None
    if tracks is None:
        raise Upstream(f"Не удалось получить запись диалога {dialog_id}")
    result = analyse(dialog.lines or [], tracks)
    store.set_prosody(dialog_id, result)
    return result
