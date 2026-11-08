"""Таблицы пакетной обработки в той же базе SQLite: задания, их диалоги по батчам, запуски батчей."""

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  priority TEXT NOT NULL CHECK (priority IN ('high', 'normal', 'low')),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'paused', 'done', 'cancelled', 'failed')),
  batch_size INTEGER NOT NULL, force INTEGER NOT NULL, note TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS batch_items (
  job_id INTEGER NOT NULL REFERENCES batch_jobs(id), dialog_id TEXT NOT NULL REFERENCES dialogs(id),
  batch INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'done', 'error')), error TEXT,
  PRIMARY KEY (job_id, dialog_id));
CREATE TABLE IF NOT EXISTS batch_runs (
  run_id INTEGER PRIMARY KEY REFERENCES runs(id), job_id INTEGER NOT NULL REFERENCES batch_jobs(id),
  batch INTEGER NOT NULL, n INTEGER NOT NULL);
"""

Priority = Literal["high", "normal", "low"]
JobStatus = Literal["queued", "running", "paused", "done", "cancelled", "failed"]
ItemStatus = Literal["queued", "done", "error"]


@dataclass(frozen=True)
class JobRow:
    id: int
    priority: Priority
    status: JobStatus
    batch_size: int
    force: bool
    note: str | None
    created: float


@dataclass(frozen=True)
class ItemRow:
    dialog_id: str
    batch: int
    status: ItemStatus
    error: str | None


@dataclass(frozen=True)
class BatchRunRow:
    """Запуск батча: n диалогов; время и цена — из строки `runs`."""

    run_id: int
    batch: int
    n: int
    started: float
    finished: float | None
    cost: float


class BatchStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.executescript(SCHEMA)

    def add_job(
        self,
        priority: Priority,
        batch_size: int,
        force: bool,
        created: float,
        batches: Sequence[Sequence[str]],
    ) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO batch_jobs (priority, batch_size, force, created) VALUES (?, ?, ?, ?)",
                (priority, batch_size, int(force), created),
            )
            job_id = cur.lastrowid
            assert job_id is not None
            self._conn.executemany(
                "INSERT INTO batch_items (job_id, dialog_id, batch) VALUES (?, ?, ?)",
                [(job_id, d, no) for no, ids in enumerate(batches, 1) for d in ids],
            )
        return job_id

    @staticmethod
    def _job(row: sqlite3.Row) -> JobRow:
        return JobRow(
            id=row["id"],
            priority=row["priority"],
            status=row["status"],
            batch_size=row["batch_size"],
            force=bool(row["force"]),
            note=row["note"],
            created=row["created"],
        )

    def jobs(self) -> list[JobRow]:
        """Новые первыми."""
        return [self._job(r) for r in self._conn.execute("SELECT * FROM batch_jobs ORDER BY id DESC")]

    def job(self, job_id: int) -> JobRow | None:
        row = self._conn.execute("SELECT * FROM batch_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row is not None else None

    def set_status(self, job_id: int, status: JobStatus, note: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE batch_jobs SET status = ?, note = ? WHERE id = ?", (status, note, job_id)
            )

    def claim(self, job_id: int) -> None:
        """Задание в работу; прежнее в работе (его обогнал приоритет) — обратно в очередь."""
        with self._conn:
            self._conn.execute(
                "UPDATE batch_jobs SET status = 'queued' WHERE status = 'running' AND id != ?", (job_id,)
            )
            self._conn.execute("UPDATE batch_jobs SET status = 'running' WHERE id = ?", (job_id,))

    def pause_unfinished(self, note: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE batch_jobs SET status = 'paused', note = ? WHERE status IN ('queued', 'running')",
                (note,),
            )

    def items(self, job_id: int) -> list[ItemRow]:
        rows = self._conn.execute(
            "SELECT dialog_id, batch, status, error FROM batch_items WHERE job_id = ? ORDER BY batch, rowid",
            (job_id,),
        )
        return [ItemRow(r["dialog_id"], r["batch"], r["status"], r["error"]) for r in rows]

    def set_items(self, job_id: int, outcomes: Mapping[str, tuple[ItemStatus, str | None]]) -> None:
        with self._conn:
            self._conn.executemany(
                "UPDATE batch_items SET status = ?, error = ? WHERE job_id = ? AND dialog_id = ?",
                [(status, error, job_id, d) for d, (status, error) in outcomes.items()],
            )

    def retry_errors(self, job_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE batch_items SET status = 'queued', error = NULL "
                "WHERE job_id = ? AND status = 'error'",
                (job_id,),
            )

    def add_batch_run(self, run_id: int, job_id: int, batch: int, n: int) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO batch_runs (run_id, job_id, batch, n) VALUES (?, ?, ?, ?)",
                (run_id, job_id, batch, n),
            )

    def batch_runs(self, job_id: int) -> list[BatchRunRow]:
        """Запуски батчей задания по порядку."""
        rows = self._conn.execute(
            "SELECT b.run_id, b.batch, b.n, r.started, r.finished, r.cost FROM batch_runs b "
            "JOIN runs r ON r.id = b.run_id WHERE b.job_id = ? ORDER BY b.run_id",
            (job_id,),
        )
        return [BatchRunRow(*tuple(r)) for r in rows]
