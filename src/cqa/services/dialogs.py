"""Reviewed mark, reason owners (review-workflow design, decision 8) and pasted dialogs."""

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from cqa.adapters.store import Store
from cqa.domain.models import IngestResult
from cqa.domain.paste import PasteError, paste_dialog
from cqa.domain.review import ASTANA
from cqa.services.datasets import logged
from cqa.services.errors import Invalid, NotFound


def set_reviewed(store: Store, dialog_id: str, reviewed: bool) -> None:
    try:
        store.set_reviewed(dialog_id, reviewed)
    except KeyError:
        raise NotFound(f"Диалог {dialog_id} не найден") from None


def save_owners(store: Store, owners: Mapping[str, str]) -> dict[str, str]:
    store.set_owners(owners)
    return store.get_owners()


def paste_text(store: Store, *, title: str, ch: Literal["chat", "call"], text: str) -> str:
    """`POST /api/dialogs/text`: сохраняет диалог из текста через `add_dialogs`, оценка не запускается."""
    try:
        dialog = paste_dialog(
            title=title,
            ch=ch,
            text=text,
            taken={d.id for d in store.list_dialogs()},
            now=datetime.now(ASTANA),
        )
    except PasteError as exc:
        raise Invalid(str(exc)) from None
    with logged(store, "paste") as save:
        save(IngestResult([dialog], {}, 0, []))
    return dialog.id
