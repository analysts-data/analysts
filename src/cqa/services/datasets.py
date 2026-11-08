"""Загрузка наборов: новые диалоги со ссылками на записи; ошибки источника проходят как есть.

Каждое поступление — строка журнала `source_syncs` своего источника: учёт, откуда и сколько пришло.
"""

import contextlib
import time
from collections.abc import Callable, Iterator

from cqa.adapters.store import Store
from cqa.domain.models import IngestResult
from cqa.services.errors import Invalid
from cqa.services.ports import DialogSource

Save = Callable[[IngestResult], dict[str, int]]


@contextlib.contextmanager
def logged(store: Store, source_id: str) -> Iterator[Save]:
    """Строка журнала `running` на время загрузки; `save` сохраняет диалоги с `source_id` и закрывает
    её как `ok` или `partial` (битые записи); исключение внутри блока закрывает её как `error`."""
    sync_id = store.start_sync(source_id)
    t0 = time.monotonic()

    def ms() -> int:
        return round((time.monotonic() - t0) * 1000)

    def save(result: IngestResult) -> dict[str, int]:
        dialogs = [
            d.model_copy(update={"source_id": source_id, "external_id": d.external_id or d.id})
            for d in result.dialogs
        ]
        added, duplicates = store.add_dialogs(dialogs, result.audio)
        skipped = duplicates + result.skipped
        store.finish_sync(sync_id, "partial" if result.errors else "ok", added, skipped, result.errors, ms())
        return {"added": added, "skipped": skipped}

    try:
        yield save
    except Exception as exc:
        store.finish_sync(sync_id, "error", 0, 0, [str(exc)], ms())
        raise


async def load_group(
    store: Store, source: DialogSource, group_id: str, url: str | None = None
) -> dict[str, int]:
    """`url` по умолчанию — ссылка, сохранённая из интерфейса; без неё источник берёт `CQA_ORG_API_URL`."""
    if not group_id.strip():
        raise Invalid("Укажите group_id")
    saved = store.org_source()
    with logged(store, "org") as save:
        return save(await source.fetch(group_id, url or (saved[0] if saved else None)))


def load_upload(store: Store, source: DialogSource, raw: bytes) -> dict[str, int]:
    if not raw:
        raise Invalid("Пустой файл")
    with logged(store, "file") as save:
        return save(source.upload(raw))
