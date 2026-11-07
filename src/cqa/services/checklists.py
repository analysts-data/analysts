"""Сохранение черновика чек-листа: проверки, новая версия, закрытие апелляций (решение 11)."""

from typing import Any

from cqa.adapters.store import Store
from cqa.domain.models import Checklist
from cqa.domain.review import diff_checklists, version_note
from cqa.services.errors import Conflict, Invalid


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
