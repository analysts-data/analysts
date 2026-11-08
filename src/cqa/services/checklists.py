"""Сохранение черновика чек-листа: проверки, новая версия, закрытие апелляций (решение 11).
Настройка без сохранения: «что если», нормировка весов, шаблоны критериев, готовые чек-листы."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from cqa.adapters.store import Store
from cqa.catalog import load
from cqa.domain.checklist_export import diff, diff_markdown, to_csv, to_html, to_markdown
from cqa.domain.models import Checklist
from cqa.domain.review import diff_checklists, effective_answers, version_note
from cqa.domain.tuning import normalize, simulate
from cqa.services.bands import current_bands
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.runs import Runner
from cqa.services.state import state_for

# ponytail: seed is the test fixture; a separate product file if the two ever diverge
SEED_CHECKLIST = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "checklist_v3.json"

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
    if errors := draft_errors(draft):
        raise Invalid("; ".join(errors.values()), fields=errors)
    diff = diff_checklists(cur, draft)
    if not diff.changed:
        return {"version": cur.version, "pending": []}
    new = draft.model_copy(update={"version": cur.version + 1})
    store.add_checklist(new, version_note(diff))
    store.close_pending_appeals([*diff.pending, *diff.removed])
    return {"version": new.version, "pending": diff.pending}


def draft_errors(draft: Checklist) -> dict[str, str]:
    """Что не даст сохранить черновик: путь поля -> текст по-русски, пусто — можно сохранять."""
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for i, c in enumerate(draft.criteria):
        p = f"criteria.{i}"
        if c.id in seen:
            errors[f"{p}.id"] = f"Повторяется id критерия {c.id}"
        seen.add(c.id)
        if not 0 <= c.sec < len(draft.sections):
            errors[f"{p}.sec"] = f"Критерий {c.id}: секции {c.sec} нет"
        if c.w < 0:
            errors[f"{p}.w"] = f"Критерий {c.id}: вес {c.w:g} меньше нуля"
        if c.channel in ("chat", "call") and not c.na:
            errors[f"{p}.na"] = f"Критерий {c.id}: для канала {c.channel} нужен na: true"
        if c.type == "scale" and not c.steps:
            errors[f"{p}.steps"] = f"Критерий {c.id}: у шкалы нет ступеней"
        elif c.type == "scale" and (
            missing := [str(s) for s in c.steps or [] if not (c.stepText or {}).get(str(s))]
        ):
            errors[f"{p}.stepText"] = f"Критерий {c.id}: нет текста ступени {', '.join(missing)}"
    return errors


def simulate_draft(store: Store, draft: Checklist) -> dict[str, Any]:
    """«Что если»: итоги, если сохранить черновик, без сохранения. Ответы берутся по смыслу критериев
    черновика — как в состоянии сразу после сохранения; `save_errors` — что не даст сохранить."""
    cur = checklist_version(store, None)
    before, appeals0 = state_for(store, cur)
    after, appeals1 = state_for(store, draft)
    # «Недостаточно данных» — вне итогов, как в отчёте для руководства
    blocked = {d.id for d in before if d.sufficiency and d.sufficiency.status == "block"}
    before = [d for d in before if d.id not in blocked]
    sim = simulate(
        cur,
        draft,
        before,
        {d.id: effective_answers(d, appeals0) for d in before},
        {d.id: effective_answers(d, appeals1) for d in after},
        current_bands(store),
    )
    return {**sim, "insufficient": len(blocked), "save_errors": draft_errors(draft)}


TRIAL_MAX = 20  # диалогов в песочнице: проба на выборке, а не новая оценка набора


def trial_draft(store: Store, runner: Runner, draft: Checklist, dialogs: list[str]) -> dict[str, Any]:
    """Песочница: оценить только новые и изменённые по смыслу критерии черновика на выбранных диалогах,
    не сохраняя версию. Ответы пишутся с отпечатками черновика: «что если» сразу сравнивает их с текущими,
    а после сохранения черновика они становятся текущими без повторной оценки."""
    picked = list(dict.fromkeys(dialogs))
    if not 1 <= len(picked) <= TRIAL_MAX:
        raise Invalid(f"Выберите от 1 до {TRIAL_MAX} диалогов для песочницы, выбрано {len(picked)}")
    if errors := draft_errors(draft):
        raise Invalid("; ".join(errors.values()), fields=errors)
    cur = checklist_version(store, None)
    pending = diff_checklists(cur, draft).pending
    if not pending:
        raise Invalid(
            "В черновике нет новых или изменённых по смыслу критериев: оценивать нечего, "
            "«Что если» показывает новые итоги сразу"
        )
    run_id = runner.start(picked, pending, checklist=draft.model_copy(update={"version": cur.version + 1}))
    return {"run_id": run_id, "criteria": pending, "dialogs": picked}


def normalize_draft(draft: Checklist) -> dict[str, Any]:
    """Черновик с весами, приведёнными к сумме 100, доли критериев в итоге и объяснение. Не сохраняет."""
    out = normalize(draft)
    return {**out, "checklist": out["checklist"].model_dump(mode="json", exclude_none=True)}


def criteria_templates(tag: str | None) -> dict[str, Any]:
    """Шаблоны критериев (src/cqa/catalog/criteria_templates.json); `tag` — только с этим тегом."""
    templates: list[dict[str, Any]] = load("criteria_templates.json")["templates"]
    return {
        "tags": sorted({t for x in templates for t in x["tags"]}),
        "templates": [t for t in templates if tag is None or tag in t["tags"]],
    }


def checklist_presets() -> list[dict[str, Any]]:
    """Готовые чек-листы целиком для импорта в черновик: первым — официальный, затем из
    src/cqa/catalog/checklist_presets.json."""
    official = json.loads(SEED_CHECKLIST.read_text(encoding="utf-8"))
    presets = [
        {
            "key": "official",
            "name": f"Официальный чек-лист v{official['version']}",
            "description": (
                "Чек-лист из задания организаторов: по нему считается файл результатов. Если правила и "
                "смысл критериев совпадут с сохранёнными ответами, они вернутся без новой оценки."
            ),
            "official": True,
            "checklist": official,
        },
        *({**p, "official": False} for p in load("checklist_presets.json")["presets"]),
    ]
    return [{**p, "criteria": len(p["checklist"]["criteria"])} for p in presets]
