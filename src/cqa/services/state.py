"""GET /api/state: everything the UI needs in one object (review-workflow design, decisions 9-10)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from cqa.adapters.jev import JEV_MODEL
from cqa.adapters.store import Store
from cqa.domain.models import Appeal, Checklist, CriterionResult, Dialog, Mode
from cqa.domain.report import build_report, to_csv, to_html, to_markdown
from cqa.domain.review import fingerprints, stamp
from cqa.domain.scores_export import Shape
from cqa.domain.scores_export import to_csv as scores_to_csv
from cqa.services.errors import Unavailable
from cqa.settings import Settings


def mode_from_settings(settings: Settings) -> Mode:
    jev = settings.evaluator == "jev"  # только Jev: модель — Jev, второго мнения нет
    return Mode(
        where=settings.data_where,
        anonymized=settings.anonymize,
        model=JEV_MODEL if jev else settings.llm_model,
        verifier=None if jev else settings.verifier,
    )


def current_results(
    store: Store, checklist: Checklist, dialogs: Sequence[Dialog]
) -> dict[str, dict[str, CriterionResult]]:
    """Results of the current meaning per dialog; a call matches the fingerprint with `call`."""
    found = {ch: store.current_results(fps) for ch, fps in fingerprints(checklist).items()}
    return {d.id: found[d.ch][d.id] for d in dialogs if d.id in found[d.ch]}


def current_state(store: Store) -> tuple[Checklist, list[Dialog], list[Appeal]]:
    """Current checklist, dialogs with current `res`, appeals the score takes into account."""
    checklist = store.current_checklist()
    if checklist is None:
        raise Unavailable("Чек-лист не загружен")
    fps = fingerprints(checklist)
    stored = store.list_dialogs()
    results = current_results(store, checklist, stored)
    dialogs = [d.model_copy(update={"res": results.get(d.id, {})}) for d in stored]
    ch = {d.id: d.ch for d in stored}
    # open records always; decided ones only for the current meaning of the criterion (decision 12)
    appeals = [
        a
        for a, fp in store.list_appeals()
        if a.status in ("pending", "closed") or fp == fps[ch[a.dlg]].get(a.cid)
    ]
    return checklist, dialogs, appeals


ReportFormat = Literal["html", "json", "md", "csv"]


def report(
    store: Store, fmt: ReportFormat, *, lang: str | None, ch: str | None, now: datetime
) -> dict[str, Any] | str:
    """Отчёт для руководства из того же состояния, что GET /api/state: json — словарь, html и md — текст."""
    checklist, dialogs, appeals = current_state(store)
    rep = build_report(checklist, dialogs, appeals, store.get_owners(), at=stamp(now), lang=lang, ch=ch)
    return rep if fmt == "json" else {"html": to_html, "md": to_markdown, "csv": to_csv}[fmt](rep)


def scores_csv(store: Store, shape: Shape, *, lang: str | None, ch: str | None) -> tuple[int, str]:
    """Оценки для Excel из того же состояния, что GET /api/state: версия чек-листа и текст CSV."""
    checklist, dialogs, appeals = current_state(store)
    return checklist.version, scores_to_csv(checklist, dialogs, appeals, shape, lang=lang, ch=ch)


def build_state(store: Store, mode: Mode) -> dict[str, Any]:
    checklist, dialogs, appeals = current_state(store)
    return {
        "checklist": checklist.model_dump(mode="json", exclude_none=True),
        "versions": store.list_versions(),
        "dialogs": [d.model_dump(mode="json", exclude_none=True) for d in dialogs],
        "appeals": [
            a.model_dump(mode="json", by_alias=True, exclude={"ask"} if a.kind == "review" else None)
            for a in appeals
        ],
        "owners": store.get_owners(),
        "mode": mode.model_dump(mode="json"),
    }
