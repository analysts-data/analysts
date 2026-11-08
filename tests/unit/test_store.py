"""Хранилище SQLite: схема, соединение, неизменяемость (группа 1, задачи 1.1–1.10)."""

import json
import sqlite3
from pathlib import Path

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Appeal, Checklist, Cost, CriterionResult, Dialog


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_connect_creates_wal_file_and_tables(tmp_path):
    path = tmp_path / "data" / "cqa.db"
    conn = connect(str(path))

    assert path.is_file()
    assert path.parent.is_dir()
    mode = conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"]
    assert mode == "wal"
    assert {"dialogs", "checklists", "results", "runs", "appeals", "owners"} <= _tables(conn)


def test_results_cannot_be_updated_or_deleted():
    conn = connect(":memory:")
    conn.execute("INSERT INTO dialogs (id, body) VALUES ('d1', '{}')")
    conn.execute(
        "INSERT INTO results (dialog_id, cid, version, fp, body, created) "
        "VALUES ('d1', '04', 3, 'f1', '{}', '2026-11-07T15:10:00+05:00')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="результаты неизменяемы"):
        conn.execute("UPDATE results SET body = '{\"a\": 1}'")
    with pytest.raises(sqlite3.IntegrityError, match="результаты неизменяемы"):
        conn.execute("DELETE FROM results")


def test_checklist_rows_cannot_be_updated():
    conn = connect(":memory:")
    conn.execute(
        "INSERT INTO checklists (version, body, note, created) "
        "VALUES (3, '{}', 'начальная версия', '2026-11-07T15:10:00+05:00')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="версии чек-листа неизменяемы"):
        conn.execute("UPDATE checklists SET note = 'x'")


def test_checks_reject_unknown_values():
    conn = connect(":memory:")
    conn.execute("INSERT INTO dialogs (id, body) VALUES ('d1', '{}')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO appeals (dlg, cid, kind, fp, status, body) "
            "VALUES ('d1', '04', 'decision', 'f1', 'pending', '{}')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO appeals (dlg, cid, kind, fp, status, body) "
            "VALUES ('d1', '04', 'appeal', 'f1', 'closed2', '{}')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO runs (total, status, started) VALUES (16, 'paused', 100.0)")


# --- Задачи 1.4–1.10: диалоги, чек-листы, результаты, запуски, апелляции, адресаты ---

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _dialogs_fixture() -> list[Dialog]:
    raw = json.loads((FIXTURES / "dialogs_prototype.json").read_text())
    return [Dialog.model_validate(d) for d in raw]


def _checklist_fixture() -> Checklist:
    return Checklist.model_validate(json.loads((FIXTURES / "checklist_v3.json").read_text()))


def _by_id(dialogs: list[Dialog], dialog_id: str) -> Dialog:
    return next(d for d in dialogs if d.id == dialog_id)


def _result(**over: object) -> CriterionResult:
    data: dict[str, object] = {
        "a": 15,
        "alt": 10,
        "ev": [9, 10],
        "seg": "реплики 30–32",
        "why": "Обоснование по-русски.",
        "quote": "дословный фрагмент",
        "tag": "Не назван срок ответа",
        "better": "Как сказать лучше.",
        "evFail": False,
        "model": "qwen3-6",
        "calls": 1,
        "cost": 0.0012,
        "ms": 2100,
    }
    data.update(over)
    return CriterionResult.model_validate(data)


def _appeal(**over: object) -> Appeal:
    data: dict[str, object] = {
        "id": "",
        "kind": "appeal",
        "dlg": "p1-ru-003",
        "cid": "04",
        "from": 5,
        "ask": 10,
        "to": None,
        "ev": [8],
        "by": "Оператор",
        "at": "07.11 15:10",
        "status": "pending",
        "comment": "Комментарий заявителя",
        "reviewer": None,
        "reason": None,
        "decidedAt": None,
    }
    data.update(over)
    return Appeal.model_validate(data)


def test_add_dialogs_counts_added_and_duplicates_in_order():
    store = Store(connect(":memory:"))
    dialogs = _dialogs_fixture()
    call, chat = _by_id(dialogs, "call-024"), _by_id(dialogs, "p1-ru-003")
    extra = chat.model_copy(update={"id": "p1-ru-025"})

    assert store.add_dialogs([call, chat], {"call-024": "https://org.test/p/1"}) == (2, 0)
    assert store.add_dialogs([call, chat, extra], {}) == (1, 2)

    assert [d.id for d in store.list_dialogs()] == ["call-024", "p1-ru-003", "p1-ru-025"]
    assert store.audio_url("call-024") == "https://org.test/p/1"
    assert store.audio_url("p1-ru-003") is None
    assert store.audio_url("nope") is None


def test_dialog_body_drops_res_and_keeps_lines():
    conn = connect(":memory:")
    store = Store(conn)
    call = _by_id(_dialogs_fixture(), "call-024")

    store.add_dialogs([call], {})

    got = store.get_dialog("call-024")
    assert got is not None
    assert got.res == {}
    assert got.reviewed is False
    assert got.cost is None
    assert conn.execute("SELECT COUNT(*) AS c FROM results").fetchone()["c"] == 0
    line = got.lines[0]
    assert line.n is not None and line.who is not None and line.text


def test_get_dialog_unknown_is_none():
    store = Store(connect(":memory:"))
    assert store.get_dialog("nope") is None


def test_set_cost_overwrites_last():
    store = Store(connect(":memory:"))
    dialogs = _dialogs_fixture()
    store.add_dialogs([_by_id(dialogs, "call-024"), _by_id(dialogs, "p1-ru-003")], {})

    store.set_cost("call-024", Cost(calls=1, verifier_calls=0, usd=0.001, ms=100))
    store.set_cost("call-024", Cost(calls=2, verifier_calls=1, usd=0.002, ms=200))

    assert store.get_dialog("call-024").cost == Cost(calls=2, verifier_calls=1, usd=0.002, ms=200)
    assert store.get_dialog("p1-ru-003").cost is None


def test_set_reviewed_marks_and_raises_for_unknown():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "call-024")], {})

    store.set_reviewed("call-024", True)
    assert store.get_dialog("call-024").reviewed is True

    with pytest.raises(KeyError):
        store.set_reviewed("nope", True)


# --- Задача 1.5: чек-листы ---


def test_add_checklist_rejects_duplicate_version():
    conn = connect(":memory:")
    store = Store(conn)
    store.add_checklist(_checklist_fixture(), "начальная версия")

    with pytest.raises(sqlite3.IntegrityError):
        store.add_checklist(_checklist_fixture(), "ещё раз")

    assert store.list_versions() == [{"v": _checklist_fixture().version, "note": "начальная версия"}]


def test_checklist_reads_any_stored_version_and_none_for_unknown():
    store = Store(connect(":memory:"))
    v3 = _checklist_fixture()
    v4 = v3.model_copy(update={"version": 4, "rules": "Новые правила"})
    store.add_checklist(v3, "начальная версия")
    store.add_checklist(v4, "изменены общие правила")

    assert store.checklist(3) == v3
    assert store.checklist(4) == v4
    assert store.checklist(5) is None


def test_current_checklist_returns_max_version():
    store = Store(connect(":memory:"))
    assert store.current_checklist() is None

    v3 = _checklist_fixture()
    v4 = v3.model_copy(update={"version": 4})
    store.add_checklist(v3, "начальная версия")
    store.add_checklist(v4, "веса или названия 06")

    assert store.current_checklist() is not None
    assert store.current_checklist().version == 4
    assert store.list_versions() == [
        {"v": 3, "note": "начальная версия"},
        {"v": 4, "note": "веса или названия 06"},
    ]


def test_checklists_survive_restart(tmp_path):
    path = str(tmp_path / "data" / "cqa.db")
    conn = connect(path)
    Store(conn).add_checklist(_checklist_fixture(), "начальная версия")
    conn.close()

    reopened = Store(connect(path))
    assert reopened.current_checklist() is not None
    assert reopened.current_checklist().version == _checklist_fixture().version
    assert reopened.list_versions() == [{"v": _checklist_fixture().version, "note": "начальная версия"}]


# --- Задача 1.6: результаты ---


def test_current_results_last_row_with_same_fp_wins():
    conn = connect(":memory:")
    store = Store(conn)
    store.add_dialogs([_by_id(_dialogs_fixture(), "call-024")], {})

    store.add_result("call-024", "04", 3, "f1", _result(a=15))
    store.add_result("call-024", "04", 3, "f1", _result(a=10))

    got = store.current_results({"04": "f1"})
    assert got["call-024"]["04"].a == 10
    assert conn.execute("SELECT COUNT(*) AS c FROM results").fetchone()["c"] == 2


def test_current_results_ignores_foreign_fp():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "call-024")], {})

    store.add_result("call-024", "04", 3, "f1", _result(a=15))

    assert store.current_results({"04": "f2"}).get("call-024", {}) == {}


def test_result_json_roundtrip():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "call-024")], {})
    full = _result()

    store.add_result("call-024", "04", 3, "f1", full)

    got = store.current_results({"04": "f1"})["call-024"]["04"]
    assert got == full


# --- Задача 1.7: запуски ---


def test_run_progress_sums_and_finish_changes_status():
    store = Store(connect(":memory:"))
    run_id = store.add_run(16, 100.0)

    store.record_progress(run_id, 8, 0.01, 8)
    store.record_progress(run_id, 8, 0.01, 8, ["p1-ru-003: timeout"])

    row = store.get_run(run_id)
    assert (row.done, row.calls) == (16, 16)
    assert row.cost == pytest.approx(0.02, abs=1e-9)
    assert row.errors == ["p1-ru-003: timeout"]
    assert row.status == "running"

    store.finish_run(run_id, 110.0, "cancelled")
    assert store.get_run(run_id).status == "cancelled"
    assert store.get_run(999) is None


def test_cancel_stale_runs_leaves_done_alone():
    store = Store(connect(":memory:"))
    done_id = store.add_run(8, 1.0)
    store.finish_run(done_id, 2.0, "done")
    running_id = store.add_run(8, 3.0)

    store.cancel_stale_runs()

    assert store.get_run(done_id).status == "done"
    assert store.get_run(running_id).status == "cancelled"


# --- Задача 1.8: апелляции ---


def test_add_appeal_assigns_ids_and_get_returns_pair():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "p1-ru-003")], {})

    a1 = store.add_appeal(_appeal(), "f04")
    a2 = store.add_appeal(_appeal(cid="06"), "f06")

    assert a1.id == "a1"
    assert a2.id == "a2"

    got, fp = store.get_appeal("a2")
    assert got is not None
    assert got.id == "a2"
    assert fp == "f06"
    assert got.model_dump(by_alias=True)["from"] == 5
    assert store.get_appeal("a999") is None


def test_save_decision_overwrites_body_and_status():
    conn = connect(":memory:")
    store = Store(conn)
    store.add_dialogs([_by_id(_dialogs_fixture(), "p1-ru-003")], {})
    a1 = store.add_appeal(_appeal(), "f04")

    decided = a1.model_copy(
        update={"status": "changed", "to": 10, "reason": "Срок назван", "reviewer": "Проверяющий"}
    )
    store.save_decision(decided)

    got, _ = store.get_appeal("a1")
    assert got.status == "changed"
    assert got.to == 10
    assert conn.execute("SELECT status FROM appeals WHERE n = 1").fetchone()["status"] == "changed"


def test_list_appeals_in_filing_order():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "p1-ru-003")], {})
    store.add_appeal(_appeal(), "f04")
    store.add_appeal(_appeal(cid="06"), "f06")

    listed = store.list_appeals()
    assert [a.id for a, _ in listed] == ["a1", "a2"]


# --- Задача 1.9: закрытие ожидающих апелляций ---


def test_close_pending_appeals_closes_only_pending_kind():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "p1-ru-003")], {})
    store.add_appeal(_appeal(), "f04")  # ожидающая, 04
    a2 = store.add_appeal(
        _appeal(
            status="changed",
            to=10,
            reason="ок",  # решённая, 04
            reviewer="Проверяющий",
            decidedAt="07.11 16:00",
        ),
        "f04",
    )
    a3 = store.add_appeal(
        _appeal(
            kind="review",
            ask=None,
            status="confirmed",  # review, 04
            to=5,
            by="Специалист КК",
            reason="ок",
            decidedAt="07.11 16:00",
        ),
        "f04",
    )
    a4 = store.add_appeal(_appeal(cid="06"), "f06")  # ожидающая, 06

    closed = store.close_pending_appeals(["04"])

    assert closed == ["a1"]
    got1, _ = store.get_appeal("a1")
    assert got1.status == "closed"
    statuses = {a.id: a.status for a, _ in store.list_appeals()}
    assert statuses == {"a1": "closed", "a2": a2.status, "a3": a3.status, "a4": a4.status}


# --- Задача 1.10: адресаты ---


def test_set_owners_rejects_unknown_value():
    conn = connect(":memory:")
    store = Store(conn)

    with pytest.raises(sqlite3.IntegrityError):
        store.set_owners({"Не назван срок ответа": "Маркетинг"})

    assert store.get_owners() == {}


def test_set_owners_upserts_each_tag():
    store = Store(connect(":memory:"))

    store.set_owners({"Не назван срок ответа": "Инструкция"})
    assert store.get_owners() == {"Не назван срок ответа": "Инструкция"}

    store.set_owners({"Переспрос известного": "Сервис"})
    assert store.get_owners() == {
        "Не назван срок ответа": "Инструкция",
        "Переспрос известного": "Сервис",
    }

    store.set_owners({"Не назван срок ответа": "Не назначено"})
    assert store.get_owners() == {
        "Не назван срок ответа": "Не назначено",
        "Переспрос известного": "Сервис",
    }


def test_org_source_is_saved_and_replaced():
    store = Store(connect(":memory:"))
    assert store.org_source() is None

    store.set_org_source("https://org.test/api?token=a", "DEV")
    store.set_org_source("https://org.test/api?token=b", "CTRL1")

    assert store.org_source() == ("https://org.test/api?token=b", "CTRL1")


# --- история оценок и запуски ---

OLD_SCHEMA = """
CREATE TABLE dialogs (id TEXT PRIMARY KEY, body TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
  audio_url TEXT, cost TEXT);
CREATE TABLE results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, dialog_id TEXT NOT NULL REFERENCES dialogs(id),
  cid TEXT NOT NULL, version INTEGER NOT NULL, fp TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, errors TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'running', started REAL NOT NULL, finished REAL);
INSERT INTO dialogs (id, body) VALUES ('d1', '{}');
INSERT INTO results (dialog_id, cid, version, fp, body, created)
  VALUES ('d1', '04', 3, 'f1', '{"a": 15}', 't');
INSERT INTO runs (total, started) VALUES (8, 1.0);
"""


def test_old_database_gains_run_columns_and_keeps_its_rows(tmp_path: Path) -> None:
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(OLD_SCHEMA)
    old.close()

    store = Store(connect(path))

    (row,) = store.result_rows(dialog_id="d1")
    assert (row.cid, row.run_id, row.result.a) == ("04", None, 15)
    run = store.get_run(1)
    assert run is not None
    assert (run.model, run.checklist_version, run.force, run.skipped) == (None, None, False, 0)
    Store(connect(path))  # second open: columns are already there


def test_result_remembers_the_run_that_gave_it():
    store = Store(connect(":memory:"))
    store.add_dialogs([_by_id(_dialogs_fixture(), "call-024")], {})
    run_id = store.add_run(1, 100.0)

    store.add_result("call-024", "04", 3, "f1", _result(a=15), run_id=run_id)
    store.add_result("call-024", "04", 3, "f1", _result(a=10, model="вручную"))

    rows = store.result_rows(dialog_id="call-024")
    assert [(r.run_id, r.result.a) for r in rows] == [(run_id, 15), (None, 10)]
    assert [r.result.a for r in store.result_rows(run_id=run_id)] == [15]
    assert store.get_result(rows[0].id) == rows[0]
    assert store.get_result(999) is None


def test_runs_remember_model_version_and_force_newest_first():
    store = Store(connect(":memory:"))
    first = store.add_run(16, 1.0, model="qwen3-6", checklist_version=3)
    second = store.add_run(4, 2.0, model="jev-latest", checklist_version=3, force=True, skipped=2)

    runs = store.list_runs()

    assert [r.id for r in runs] == [second, first]
    assert (runs[0].model, runs[0].checklist_version, runs[0].force, runs[0].skipped) == (
        "jev-latest",
        3,
        True,
        2,
    )
    assert (runs[1].force, runs[1].skipped) == (False, 0)
