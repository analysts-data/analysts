"""Reviewed mark and reason owners (review-workflow design, decision 8)."""

from cqa.adapters.store import Store
from cqa.services.errors import NotFound


def set_reviewed(store: Store, dialog_id: str, reviewed: bool) -> None:
    try:
        store.set_reviewed(dialog_id, reviewed)
    except KeyError:
        raise NotFound(f"Диалог {dialog_id} не найден") from None
