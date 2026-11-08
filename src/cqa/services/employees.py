"""Справочник сотрудников и обзор работы: действия из журнала, решения по апелляциям, открытая нагрузка."""

import csv
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Literal, get_args

from cqa.adapters.store import Store
from cqa.domain.review import ASTANA
from cqa.services.errors import Invalid
from cqa.services.state import report

Role = Literal["operator", "qa", "reviewer", "manager", "admin"]
ROLES = get_args(Role)
# счётчики обзора за всё время журнала: поле -> действия
COUNTED = {
    "appeals_filed": ("appeal.file",),
    "decisions": ("appeal.decide", "review.decide"),
    "manual_answers": ("answer.manual",),
    "checklist_saves": ("checklist.save",),
    "dialogs_reviewed": ("dialog.reviewed",),
}


def put_employee(
    store: Store, employee_id: str, *, name: str, role: str, team: str, active: bool
) -> dict[str, Any]:
    if not employee_id.strip() or not name.strip():
        raise Invalid("Нужны id и имя сотрудника")
    if role not in ROLES:
        raise Invalid(f"Роль {role} неизвестна: {', '.join(ROLES)}")
    store.put_employees(
        [{"id": employee_id, "name": name.strip(), "role": role, "team": team.strip(), "active": active}]
    )
    found = store.employee(employee_id)
    assert found is not None
    return found


def import_csv(store: Store, raw: bytes) -> dict[str, int]:
    """`id;name;role;team`, первая строка `id;…` — заголовок. Ошибка в строке — 422, ничего не сохранено."""
    if not raw.strip():
        raise Invalid("Пустой файл")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("Файл не в UTF-8") from None
    rows = []
    for n, cells in enumerate(csv.reader(text.splitlines(), delimiter=";"), start=1):
        if not any(c.strip() for c in cells) or (n == 1 and cells[0].strip().lower() == "id"):
            continue
        emp_id, name, role, team = (c.strip() for c in [*cells, "", "", ""][:4])
        if not emp_id or not name:
            raise Invalid(f"Строка {n}: нужны id и имя")
        if role not in ROLES:
            raise Invalid(f"Строка {n}: роль {role or '—'} неизвестна, допустимы {', '.join(ROLES)}")
        rows.append({"id": emp_id, "name": name, "role": role, "team": team, "active": True})
    known = {e["id"] for e in store.employees()}
    store.put_employees(rows)
    added = len({r["id"] for r in rows} - known)
    return {"added": added, "updated": len({r["id"] for r in rows}) - added}


def _by_actor(counts: list[tuple[str | None, str, int]]) -> dict[str | None, dict[str, int]]:
    out: dict[str | None, dict[str, int]] = defaultdict(dict)
    for actor_id, action, n in counts:
        out[actor_id][action] = n
    return out


def _minutes(at: str, decided: str) -> float:
    """Метки апелляций «дд.мм чч:мм» без года; решение после Нового года — плюс год."""
    first, last = (datetime.strptime(f"2000 {s}", "%Y %d.%m %H:%M") for s in (at, decided))
    delta = (last - first).total_seconds() / 60
    return (
        delta if delta >= 0 else delta + 366 * 24 * 60
    )  # ponytail: високосный 2000, ошибка ±сутки раз в год


def _decision_minutes(store: Store) -> dict[str, list[float]]:
    appeals = {a.id: a for a, _ in store.list_appeals()}
    out: dict[str, list[float]] = defaultdict(list)
    for entry in store.audit(action="appeal.decide"):
        appeal = appeals.get(entry["target_id"])
        if entry["actor_id"] and appeal is not None and appeal.decidedAt:
            out[entry["actor_id"]].append(_minutes(appeal.at, appeal.decidedAt))
    return out


def overview(store: Store, now: datetime) -> dict[str, Any]:
    """`GET /api/overview`: действия сотрудников за сегодня и 7 дней, счётчики, медиана решения, нагрузка."""
    day = now.astimezone(ASTANA).date()
    today = _by_actor(store.audit_counts(day.isoformat()))
    week = _by_actor(store.audit_counts((day - timedelta(days=6)).isoformat()))
    total = _by_actor(store.audit_counts())
    waits = _decision_minutes(store)
    people = []
    for e in store.employees():
        done = total.get(e["id"], {})
        people.append(
            {
                **e,
                "today": today.get(e["id"], {}),
                "week": week.get(e["id"], {}),
                **{k: sum(done.get(a, 0) for a in actions) for k, actions in COUNTED.items()},
                "median_decision_min": round(median(w), 1) if (w := waits.get(e["id"])) else None,
            }
        )
    teams: dict[str, dict[str, Any]] = {}
    for p in people:
        t = teams.setdefault(
            p["team"], {"team": p["team"], "employees": 0, "today": 0, "week": 0, **dict.fromkeys(COUNTED, 0)}
        )
        t["employees"] += 1
        t["today"] += sum(p["today"].values())
        t["week"] += sum(p["week"].values())
        for k in COUNTED:
            t[k] += p[k]
    summary = report(store, "json", lang=None, ch=None, now=now)
    assert isinstance(summary, dict)
    return {
        "at": now.astimezone(ASTANA).isoformat(timespec="seconds"),
        "employees": people,
        "teams": sorted(teams.values(), key=lambda t: t["team"]),
        "unattributed": {
            "today": sum(today.get(None, {}).values()),
            "week": sum(week.get(None, {}).values()),
        },
        "workload": {
            "pending_appeals": summary["summary"]["open_appeals"],
            "needs_review": summary["summary"]["needs_review"],
            "unreviewed": sum(not d.reviewed for d in store.list_dialogs()),
        },
    }
