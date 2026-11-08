"""Reviewed mark, reason owners (review-workflow design, decision 8), pasted dialogs, operators."""

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from cqa.adapters.store import Store
from cqa.domain.ingest import parse_operator_csv
from cqa.domain.paste import PasteError, paste_dialog
from cqa.domain.review import ASTANA
from cqa.services.errors import Invalid, NotFound


def set_reviewed(store: Store, dialog_id: str, reviewed: bool) -> None:
    try:
        store.set_reviewed(dialog_id, reviewed)
    except KeyError:
        raise NotFound(f"Диалог {dialog_id} не найден") from None


def set_operator(store: Store, dialog_id: str, operator: str | None) -> str | None:
    """`PUT /api/dialogs/{id}/operator`: пустое имя снимает назначение."""
    name = (operator or "").strip() or None
    try:
        store.set_operator(dialog_id, name)
    except KeyError:
        raise NotFound(f"Диалог {dialog_id} не найден") from None
    return name


def import_operators(store: Store, raw: bytes) -> dict[str, object]:
    """`POST /api/operators/import`: CSV `conversation_id;operator` в UTF-8, одна транзакция."""
    try:
        pairs = parse_operator_csv(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise Invalid("Файл не в UTF-8") from None
    if not pairs:
        raise Invalid("Нет строк вида conversation_id;operator")
    updated, unknown = store.set_operators(pairs)
    return {"updated": updated, "unknown_ids": unknown}


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
    store.add_dialogs([dialog], {})
    return dialog.id
