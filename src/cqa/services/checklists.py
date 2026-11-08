"""Сохранение черновика чек-листа: проверки, новая версия, закрытие апелляций (решение 11)."""

from collections.abc import Callable
from typing import Any, Literal

from cqa.adapters.store import Store
from cqa.domain.checklist_export import diff, diff_markdown, to_csv, to_html, to_markdown
from cqa.domain.models import Checklist
from cqa.domain.review import diff_checklists, version_note
from cqa.services.errors import Conflict, Invalid, NotFound

ExportFormat = Literal["json", "csv", "md", "html"]
DiffFormat = Literal["json", "md"]
RENDER: dict[str, Callable[[Checklist], str]] = {
    "json": lambda cl: cl.model_dump_json(indent=2, exclude_none=True),  # как checklist в GET /api/state
    "csv": to_csv,
    "md": to_markdown,
    "html": to_html,
}


def checklist_version(store: Store, v: int | None) -> Checklist:
    """Версия v, без v — текущая; неизвестная — NotFound."""
    cl = store.current_checklist() if v is None else store.checklist(v)
    if cl is None:
        raise NotFound(f"Версии чек-листа v{v} нет")
    return cl


def export_checklist(store: Store, v: int | None, fmt: ExportFormat) -> tuple[int, str]:
    """(номер версии, текст файла)."""
    cl = checklist_version(store, v)
    return cl.version, RENDER[fmt](cl)


def _compare(old: Checklist, new: Checklist, fmt: DiffFormat) -> dict[str, Any] | str:
    return diff(old, new) if fmt == "json" else diff_markdown(old, new)


def diff_versions(store: Store, frm: int, to: int | None, fmt: DiffFormat) -> dict[str, Any] | str:
    return _compare(checklist_version(store, frm), checklist_version(store, to), fmt)


def diff_draft(store: Store, draft: Checklist, fmt: DiffFormat) -> dict[str, Any] | str:
    """«Что изменится»: текущая версия против черновика, который сохранится как cur + 1. Ничего не пишет."""
    cur = checklist_version(store, None)
    return _compare(cur, draft.model_copy(update={"version": cur.version + 1}), fmt)


def save_checklist(store: Store, draft: Checklist) -> dict[str, Any]:
    """Сохранить черновик как версию cur + 1. Ответ: {"version", "pending"}."""
    cur = store.current_checklist()
    if cur is None:
        raise Conflict("Чек-лист ещё не создан")  # недостижимо: create_app сеет начальную версию
    if draft.version != cur.version:
        raise Conflict(
            f"Черновик основан на v{draft.version}, текущая версия v{cur.version}. Обновите страницу."
        )
    seen: set[str] = set()
    for c in draft.criteria:
        if c.id in seen:
            raise Invalid(f"Повторяется id критерия {c.id}")
        seen.add(c.id)
        if not 0 <= c.sec < len(draft.sections):
            raise Invalid(f"Критерий {c.id}: секции {c.sec} нет")
        if c.type == "scale" and not c.steps:
            raise Invalid(f"Критерий {c.id}: у шкалы нет ступеней")
        if c.channel in ("chat", "call") and not c.na:
            raise Invalid(f"Критерий {c.id}: для канала {c.channel} нужен na: true")
        if c.type == "scale" and not c.steps:
            raise Invalid(f"Критерий {c.id}: у шкалы нет ступеней")
        if c.type == "scale" and (
            missing := [str(s) for s in c.steps or [] if not (c.stepText or {}).get(str(s))]
        ):
            raise Invalid(f"Критерий {c.id}: нет текста ступени {', '.join(missing)}")
    diff = diff_checklists(cur, draft)
    if not diff.changed:
        return {"version": cur.version, "pending": []}
    new = draft.model_copy(update={"version": cur.version + 1})
    store.add_checklist(new, version_note(diff))
    store.close_pending_appeals([*diff.pending, *diff.removed])
    return {"version": new.version, "pending": diff.pending}
