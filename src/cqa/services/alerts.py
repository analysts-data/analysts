"""Маркеры диалогов и алерты: каталог маркеров, ручные маркеры, правила, оценка с дедупликацией, статусы."""

from collections import Counter
from datetime import datetime
from typing import Any

from cqa.adapters.store import Store
from cqa.domain.alerts import CATALOG, MOVES, SEVERITIES, STATUSES, check_alerts, check_rules
from cqa.domain.review import stamp
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.state import alert_rules, current_state, dialog_views

STATUS_RU = {"new": "новый", "ack": "принят", "resolved": "закрыт"}


def catalog(store: Store) -> list[str]:
    stored: list[str] | None = store.get_list("markers_catalog")
    return list(CATALOG) if stored is None else stored


def check_catalog(raw: Any) -> list[dict[str, Any]]:
    """Ошибки по полям `PUT /api/markers/catalog`: список непустых неповторяющихся строк до 40 символов."""
    if not isinstance(raw, list):
        return [{"loc": ["body"], "msg": "Нужен список подписей маркеров"}]
    errors, seen = [], set()
    for i, label in enumerate(raw):
        if not isinstance(label, str) or not label.strip() or len(label) > 40:
            errors.append({"loc": ["body", i], "msg": "Подпись маркера — непустая строка до 40 символов"})
        elif label in seen:
            errors.append({"loc": ["body", i], "msg": f"Маркер «{label}» повторяется"})
        else:
            seen.add(label)
    return errors


def put_catalog(store: Store, labels: list[str]) -> list[str]:
    store.set_list("markers_catalog", labels)
    return labels


def change_markers(
    store: Store, dialog_id: str, *, add: list[str], remove: list[str], by: str, now: datetime
) -> list[dict[str, Any]]:
    """Поставить и снять ручные маркеры; возвращает все маркеры диалога, автоматические первыми."""
    if store.get_dialog(dialog_id) is None:
        raise NotFound(f"Диалог {dialog_id} не найден")
    unknown = [label for label in add if label not in catalog(store)]
    if unknown:
        raise Invalid(f"Маркеров нет в списке: {', '.join(unknown)}. Добавьте их в список маркеров")
    store.change_markers(dialog_id, add, remove, by, stamp(now))
    return markers_of(store, dialog_id)


def markers_of(store: Store, dialog_id: str) -> list[dict[str, Any]]:
    checklist, dialogs, appeals = current_state(store)
    picked = [d for d in dialogs if d.id == dialog_id]
    return dialog_views(store, checklist, picked, appeals)[0].markers


def rules_out(store: Store) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in alert_rules(store)]


def put_rules(store: Store, raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(правила после сохранения, ошибки по полям). При ошибках ничего не сохраняется."""
    rules, errors = check_rules(raw, catalog(store))
    if errors:
        return [], errors
    store.set_list("alert_rules", [r.model_dump(mode="json") for r in rules])
    return rules_out(store), []


def refresh(store: Store, now: datetime) -> list[dict[str, Any]]:
    """Проверить правила на текущих данных и записать новые алерты; повтор (правило, цель) пропускается."""
    checklist, dialogs, appeals = current_state(store)
    views = dialog_views(store, checklist, dialogs, appeals)
    runs = [(r.id, r.status, r.errors) for r in store.list_runs()]  # последние 50 запусков
    hits = check_alerts(alert_rules(store), views, appeals, runs, now)
    return store.add_alerts(hits, now.isoformat(timespec="seconds"))


def list_alerts(store: Store, status: str | None, severity: str | None) -> dict[str, Any]:
    """Алерты новыми первыми и счётчики колокольчика: по статусам и по важности среди незакрытых."""
    every = store.list_alerts()
    by_status = Counter(a["status"] for a in every)
    by_severity = Counter(a["severity"] for a in every if a["status"] != "resolved")
    return {
        "alerts": [a for a in every if status in (None, a["status"]) and severity in (None, a["severity"])],
        "counts": {**{s: by_status[s] for s in STATUSES}, **{s: by_severity[s] for s in SEVERITIES}},
    }


def _alert(store: Store, alert_id: int) -> dict[str, Any]:
    alert = store.get_alert(alert_id)
    if alert is None:
        raise NotFound(f"Алерт {alert_id} не найден")
    return alert


def move(store: Store, alert_id: int, to: str, *, by: str, note: str = "", now: datetime) -> dict[str, Any]:
    """new → ack → resolved (или сразу new → resolved); закрытие — с заметкой, что сделано."""
    alert = _alert(store, alert_id)
    if alert["status"] not in MOVES[to]:
        raise Conflict(f"Алерт {alert_id} уже {STATUS_RU[alert['status']]}: «{STATUS_RU[to]}» недоступно")
    at = now.isoformat(timespec="seconds")
    if to == "ack":
        store.update_alert(alert_id, status="ack", acked_by=by, acked_at=at)
    else:
        if not note.strip():
            raise Invalid("Опишите, что сделано: заметка к закрытию обязательна")
        store.update_alert(alert_id, status="resolved", resolved_by=by, resolved_at=at, note=note.strip())
    return _alert(store, alert_id)


def assign(store: Store, alert_id: int, assignee: str | None) -> dict[str, Any]:
    if _alert(store, alert_id)["status"] == "resolved":
        raise Conflict(f"Алерт {alert_id} уже закрыт: ответственного не назначить")
    store.update_alert(alert_id, assignee=(assignee or "").strip() or None)
    return _alert(store, alert_id)
