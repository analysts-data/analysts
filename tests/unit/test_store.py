"""Хранилище SQLite: схема, соединение, неизменяемость (группа 1, задачи 1.1–1.10)."""

import sqlite3

import pytest

from cqa.adapters.store import connect


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
