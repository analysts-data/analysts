"""Сотрудники, журнал действий и обзор работы: сервисы без HTTP."""

import sqlite3
from datetime import datetime
from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Appeal
from cqa.domain.review import ASTANA
from cqa.services.audit import ANONYMOUS, Actor, audit_log, record
from cqa.services.employees import ROLES, import_csv, overview, put_employee
from cqa.services.errors import Invalid
from fakes import FIXTURES

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=ASTANA)
CSV = "\ufeffid;name;role;team\ne1;Алия Тестова;operator;Линия 1\ne2;Борис Пробный;reviewer;Контроль\n"
QA = Actor("e3", "Вера Образцова", "qa")


def row(at: str, actor_id: str | None, action: str, target_id: str = "") -> dict[str, Any]:
    return {
        "at": at,
        "actor_id": actor_id,
        "actor_name": actor_id or ANONYMOUS,
        "role": "",
        "action": action,
        "target_type": "appeal",
        "target_id": target_id,
        "details": {},
    }


def test_record_drops_secret_fields_at_any_depth(store: Store) -> None:
    details = {"label": "Локальная", "key": "sk-live-1", "nested": [{"jev_api_key": "jev-2", "ok": 1}]}
    record(store, QA, "provider.save", "provider", "local", details)

    [entry] = audit_log(store, "json")
    assert entry["details"] == {"label": "Локальная", "nested": [{"ok": 1}]}
    assert (entry["actor_id"], entry["actor_name"], entry["role"]) == ("e3", "Вера Образцова", "qa")
    assert "sk-live-1" not in audit_log(store, "csv") and "jev-2" not in str(entry)


def test_audit_is_append_only(store: Store, conn: sqlite3.Connection) -> None:
    record(store, QA, "checklist.save", "checklist", 4)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit SET action = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit")


def test_audit_log_filters_newest_first_and_csv_is_excel_safe(store: Store) -> None:
    store.add_audit(row("2026-11-07T10:00:00+05:00", "e1", "appeal.file", "a1"))
    store.add_audit(row("2026-11-08T09:00:00+05:00", "e2", "appeal.decide", "a1"))
    store.add_audit(row("2026-11-08T10:00:00+05:00", "e1", "export", "=cmd"))

    assert [e["target_id"] for e in audit_log(store, "json")] == ["=cmd", "a1", "a1"]
    assert [e["action"] for e in audit_log(store, "json", actor="e1")] == ["export", "appeal.file"]
    assert [e["actor_id"] for e in audit_log(store, "json", action="appeal.decide")] == ["e2"]
    assert len(audit_log(store, "json", since="2026-11-08")) == 2
    assert len(audit_log(store, "json", limit=1)) == 1
    text = audit_log(store, "csv")
    assert isinstance(text, str) and text.startswith("\ufeffid;at;actor_id;actor_name;role;action;")
    assert ";'=cmd;" in text


def test_import_csv_adds_then_updates_and_reactivates(store: Store) -> None:
    assert import_csv(store, CSV.encode()) == {"added": 2, "updated": 0}
    put_employee(store, "e1", name="Алия Тестова", role="operator", team="Линия 1", active=False)

    assert import_csv(store, b"e1;\xd0\x90\xd0\xbb\xd0\xb8\xd1\x8f;qa;\n") == {"added": 0, "updated": 1}
    assert store.employee("e1") == {"id": "e1", "name": "Алия", "role": "qa", "team": "", "active": True}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "Пустой файл"),
        (b"\xff\xfe", "UTF-8"),
        ("e1;Имя;boss;Линия\n".encode(), "Строка 1: роль boss"),
        (b"id;name;role;team\ne1;;qa;\n", "Строка 2: нужны id и имя"),
    ],
)
def test_import_csv_rejects_bad_rows_without_saving(store: Store, raw: bytes, message: str) -> None:
    with pytest.raises(Invalid, match=message):
        import_csv(store, raw)
    assert store.employees() == []


def test_overview_counts_actions_decisions_and_workload(store: Store) -> None:
    import_csv(store, CSV.encode())
    filed = {"kind": "appeal", "dlg": "p1-ru-003", "cid": "04", "from": 5, "ask": 10, "by": "Алия Тестова"}
    a1 = store.add_appeal(
        Appeal.model_validate({**filed, "id": "", "at": "08.11 10:00", "status": "pending"}), "fp"
    )
    store.save_decision(a1.model_copy(update={"status": "changed", "to": 10, "decidedAt": "08.11 10:30"}))
    a2 = store.add_appeal(
        Appeal.model_validate({**filed, "id": "", "at": "01.11 09:00", "status": "pending"}), "fp"
    )
    store.save_decision(a2.model_copy(update={"status": "confirmed", "to": 5, "decidedAt": "01.11 10:30"}))
    store.add_appeal(
        Appeal.model_validate({**filed, "cid": "05", "id": "", "at": "08.11 11:00", "status": "pending"}),
        "fp",
    )
    store.add_audit(row("2026-11-08T10:00:00+05:00", "e1", "appeal.file", "a1"))
    store.add_audit(row("2026-11-08T10:30:00+05:00", "e2", "appeal.decide", a1.id))
    store.add_audit(row("2026-11-01T10:30:00+05:00", "e2", "appeal.decide", a2.id))
    store.add_audit(row("2026-11-05T12:00:00+05:00", "e2", "dialog.reviewed"))
    store.add_audit(row("2026-11-08T12:00:00+05:00", None, "dataset.upload"))

    out = overview(store, NOW)

    alia, boris = out["employees"]
    assert (alia["name"], alia["today"], alia["appeals_filed"]) == ("Алия Тестова", {"appeal.file": 1}, 1)
    assert boris["today"] == {"appeal.decide": 1}
    assert boris["week"] == {"appeal.decide": 1, "dialog.reviewed": 1}
    assert (boris["decisions"], boris["dialogs_reviewed"], boris["median_decision_min"]) == (2, 1, 60.0)
    assert alia["median_decision_min"] is None
    assert [(t["team"], t["employees"], t["week"]) for t in out["teams"]] == [
        ("Контроль", 1, 2),
        ("Линия 1", 1, 1),
    ]
    assert out["unattributed"] == {"today": 1, "week": 1}
    assert out["workload"] == {"pending_appeals": 1, "needs_review": 0, "unreviewed": 2}


def test_demo_employees_import_with_every_role(store: Store) -> None:
    raw = (FIXTURES.parent / "e2e" / "fixtures" / "employees.csv").read_bytes()
    assert import_csv(store, raw) == {"added": 10, "updated": 0}
    assert {e["role"] for e in store.employees()} == set(ROLES)
