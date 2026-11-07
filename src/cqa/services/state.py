"""GET /api/state: everything the UI needs in one object (review-workflow design, decisions 9-10)."""

from typing import Any

from cqa.adapters.store import Store
from cqa.domain.models import Mode
from cqa.domain.review import fingerprint
from cqa.services.errors import Unavailable
from cqa.settings import Settings


def mode_from_settings(settings: Settings) -> Mode:
    return Mode(
        where=settings.data_where,
        anonymized=settings.anonymize,
        model=settings.llm_model,
        verifier=settings.verifier,
    )


def build_state(store: Store, mode: Mode) -> dict[str, Any]:
    checklist = store.current_checklist()
    if checklist is None:
        raise Unavailable("Чек-лист не загружен")
    fps = {c.id: fingerprint(checklist, c) for c in checklist.criteria}
    results = store.current_results(fps)
    dialogs = [
        d.model_copy(update={"res": results.get(d.id, {})}).model_dump(mode="json", exclude_none=True)
        for d in store.list_dialogs()
    ]
    # open records always; decided ones only for the current meaning of the criterion (decision 12)
    appeals = [
        a.model_dump(mode="json", by_alias=True, exclude={"ask"} if a.kind == "review" else None)
        for a, fp in store.list_appeals()
        if a.status in ("pending", "closed") or fp == fps.get(a.cid)
    ]
    return {
        "checklist": checklist.model_dump(mode="json", exclude_none=True),
        "versions": store.list_versions(),
        "dialogs": dialogs,
        "appeals": appeals,
        "owners": store.get_owners(),
        "mode": mode.model_dump(mode="json"),
    }
