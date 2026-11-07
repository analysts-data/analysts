"""Запуски оценки: план пар без текущего результата, диалоги по порядку, отмена и продолжение."""

from cqa.adapters.store import Store
from cqa.domain.models import Checklist, Criterion, Dialog
from cqa.domain.review import fingerprint


def eta_seconds(done: int, total: int, elapsed: float) -> int | None:
    if done >= total:
        return 0
    if done == 0:
        return None
    return round(elapsed / done * (total - done))


def plan_run(
    store: Store, checklist: Checklist, dialogs: list[str] | None, criteria: list[str] | None
) -> list[tuple[Dialog, list[Criterion]]]:
    """Пары без результата текущего смысла в порядке `dialogs` (None — порядок добавления).

    Неизвестные id пропускаются: их отсеивает `Runner.start`.
    """
    fps = {c.id: fingerprint(checklist, c) for c in checklist.criteria}
    current = store.current_results(fps)
    chosen = [c for c in checklist.criteria if criteria is None or c.id in criteria]
    if dialogs is None:
        items = store.list_dialogs()
    else:
        items = [d for d in map(store.get_dialog, dict.fromkeys(dialogs)) if d is not None]
    plan = []
    for dialog in items:
        todo = [c for c in chosen if c.id not in current.get(dialog.id, {})]
        if todo:
            plan.append((dialog, todo))
    return plan
