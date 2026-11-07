"""Загрузка наборов: новые диалоги со ссылками на записи; ошибки источника проходят как есть."""

from cqa.adapters.store import Store
from cqa.domain.models import IngestResult
from cqa.services.errors import Invalid
from cqa.services.ports import DialogSource


def _save(store: Store, result: IngestResult) -> dict[str, int]:
    added, duplicates = store.add_dialogs(result.dialogs, result.audio)
    return {"added": added, "skipped": duplicates + result.skipped}


async def load_group(store: Store, source: DialogSource, group_id: str) -> dict[str, int]:
    if not group_id.strip():
        raise Invalid("Укажите group_id")
    return _save(store, await source.fetch(group_id))


def load_upload(store: Store, source: DialogSource, raw: bytes) -> dict[str, int]:
    if not raw:
        raise Invalid("Пустой файл")
    return _save(store, source.upload(raw))
