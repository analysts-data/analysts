"""GET /api/state: everything the UI needs in one object (review-workflow design, decisions 9-10)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from cqa.adapters.jev import JEV_MODEL
from cqa.adapters.store import Store
from cqa.domain.alerts import DEFAULT_RULES, AlertRule, DialogView, dialog_view
from cqa.domain.models import Appeal, Checklist, CriterionResult, Dialog, Mode
from cqa.domain.recommend import for_checklist, for_manager, for_operator, for_qa
from cqa.domain.report import (
    DEFINITIONS,
    MIN_SCORED,
    build_report,
    operator_card,
    operators,
    product_stats,
    to_csv,
    to_html,
    to_markdown,
)
from cqa.domain.review import fingerprints, stamp
from cqa.domain.scores_export import Shape
from cqa.domain.scores_export import to_csv as scores_to_csv
from cqa.domain.sufficiency import mark_unsupported
from cqa.services.errors import Invalid, NotFound, Unavailable
from cqa.services.sufficiency import assess_dialogs
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
    """Current checklist, dialogs with current `res` and `sufficiency`, appeals the score takes into account.

    Достаточность и пометка «ответ без основания» считаются здесь, при чтении: смена исходов правил
    сразу видна везде — в состоянии, очереди, отчёте, экспорте и файле результатов.
    """
    checklist = store.current_checklist()
    if checklist is None:
        raise Unavailable("Чек-лист не загружен")
    fps = fingerprints(checklist)
    stored = store.list_dialogs()
    results = current_results(store, checklist, stored)
    verdicts = assess_dialogs(store, stored)
    dialogs = [
        d.model_copy(
            update={
                "res": mark_unsupported(results.get(d.id, {}), verdicts[d.id]),
                "sufficiency": verdicts[d.id],
            }
        )
        for d in stored
    ]
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
    store: Store,
    fmt: ReportFormat,
    *,
    lang: str | None,
    ch: str | None,
    now: datetime,
    operator: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | str:
    """Отчёт для руководства из того же состояния, что GET /api/state: json — словарь, html и md — текст."""
    checklist, dialogs, appeals = current_state(store)
    names = {s["id"]: s["name"] for s in store.sources()}
    rep = build_report(
        checklist, dialogs, appeals, store.get_owners(), at=stamp(now), lang=lang, ch=ch, operator=operator,
        source=source, source_names=names, products=store.products() or [],
    )  # fmt: skip
    return rep if fmt == "json" else {"html": to_html, "md": to_markdown, "csv": to_csv}[fmt](rep)


def product_stats_of(store: Store) -> list[dict[str, Any]]:
    """`GET /api/products/stats` из того же состояния, что GET /api/state и отчёт."""
    checklist, dialogs, appeals = current_state(store)
    return product_stats(checklist, dialogs, appeals, store.get_owners(), store.products() or [])


Audience = Literal["operator", "qa", "manager", "checklist"]


def recommendations(store: Store, audience: Audience, operator: str | None) -> dict[str, Any]:
    """Рекомендации из того же состояния, что GET /api/state; очереди — сохранённая интонация звонков."""
    checklist, dialogs, appeals = current_state(store)
    if audience == "operator":
        if not operator:
            raise Invalid("Укажите сотрудника: for=operator&id=<имя>")
        rec = for_operator(checklist, dialogs, appeals, operator)
        if rec is None:
            raise NotFound(f"Нет диалогов сотрудника {operator}")
        return rec
    if audience == "qa":
        sound = {d.id: p for d in dialogs if d.ch == "call" and (p := store.prosody(d.id)) is not None}
        return for_qa(checklist, dialogs, appeals, sound)
    if audience == "manager":
        return for_manager(checklist, dialogs, appeals, store.get_owners())
    return for_checklist(checklist, dialogs, appeals)


def alert_rules(store: Store) -> list[AlertRule]:
    """Правила алертов из базы (`PUT /api/alerts/rules` сохраняет уже проверенные), иначе по умолчанию."""
    raw = store.get_list("alert_rules")
    return list(DEFAULT_RULES) if raw is None else [AlertRule.model_validate(r) for r in raw]


def dialog_views(
    store: Store, checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]
) -> list[DialogView]:
    """Итог и маркеры каждого диалога; пороги маркеров — из правил алертов."""
    rules, manual, prosody = alert_rules(store), store.markers(), store.all_prosody()
    return [
        dialog_view(
            checklist, d, appeals, prosody=prosody.get(d.id), manual=manual.get(d.id, []), rules=rules
        )
        for d in dialogs
    ]


def operator_rows(store: Store) -> dict[str, Any]:
    return {"definitions": DEFINITIONS, "min_n": MIN_SCORED, "operators": operators(*current_state(store))}


def operator_page(store: Store, name: str) -> dict[str, Any]:
    checklist, dialogs, appeals = current_state(store)
    card = operator_card(checklist, dialogs, appeals, store.get_owners(), name)
    if card is None:
        raise NotFound(f"Сотрудник {name} не найден")
    return {**card, "definitions": DEFINITIONS, "min_n": MIN_SCORED}


def scores_csv(store: Store, shape: Shape, *, lang: str | None, ch: str | None) -> tuple[int, str]:
    """Оценки для Excel из того же состояния, что GET /api/state: версия чек-листа и текст CSV."""
    checklist, dialogs, appeals = current_state(store)
    return checklist.version, scores_to_csv(checklist, dialogs, appeals, shape, lang=lang, ch=ch)


def build_state(store: Store, mode: Mode) -> dict[str, Any]:
    checklist, dialogs, appeals = current_state(store)
    markers = [v.markers for v in dialog_views(store, checklist, dialogs, appeals)]
    status = store.latest_dialog_status()  # eval_status: диалог в последнем запуске, где он был
    return {
        "checklist": checklist.model_dump(mode="json", exclude_none=True),
        "versions": store.list_versions(),
        "dialogs": [
            {**d.model_dump(mode="json", exclude_none=True), "eval_status": status.get(d.id), "markers": m}
            for d, m in zip(dialogs, markers, strict=True)
        ],
        "appeals": [
            a.model_dump(mode="json", by_alias=True, exclude={"ask"} if a.kind == "review" else None)
            for a in appeals
        ],
        "owners": store.get_owners(),
        "mode": mode.model_dump(mode="json"),
        # подписи для фильтра и плашки источника; полный реестр — GET /api/sources
        "sources": [
            {"id": s["id"], "name": s["name"], "kind": s["kind"], "service": s["service"]}
            for s in store.sources()
            if not s["archived"]
        ],
    }
