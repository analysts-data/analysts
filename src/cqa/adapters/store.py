"""Хранилище SQLite: один файл, режим WAL, неизменяемые версии и результаты."""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cqa.domain.models import Appeal, Checklist, Cost, CriterionResult, Dialog

SCHEMA = """
CREATE TABLE IF NOT EXISTS dialogs (
  id TEXT PRIMARY KEY, body TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
  audio_url TEXT, cost TEXT);
CREATE TABLE IF NOT EXISTS checklists (
  version INTEGER PRIMARY KEY, body TEXT NOT NULL, note TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, dialog_id TEXT NOT NULL REFERENCES dialogs(id),
  cid TEXT NOT NULL, version INTEGER NOT NULL, fp TEXT NOT NULL,
  body TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS results_pair ON results(dialog_id, cid, fp);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, errors TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'cancelled')),
  started REAL NOT NULL, finished REAL);
CREATE TABLE IF NOT EXISTS appeals (
  n INTEGER PRIMARY KEY AUTOINCREMENT, dlg TEXT NOT NULL REFERENCES dialogs(id), cid TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('appeal', 'review')), fp TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'changed', 'closed')),
  body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS owners (
  tag TEXT PRIMARY KEY,
  owner TEXT NOT NULL CHECK (owner IN ('Не назначено', 'Инструкция', 'Сервис', 'Продукт')));
CREATE TABLE IF NOT EXISTS overrides (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS org_source (
  id INTEGER PRIMARY KEY CHECK (id = 1), url TEXT NOT NULL, group_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prosody (dialog_id TEXT PRIMARY KEY REFERENCES dialogs(id), body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automation (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automation_cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT NOT NULL, body TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
  BEGIN SELECT RAISE(ABORT, 'результаты неизменяемы'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
  BEGIN SELECT RAISE(ABORT, 'результаты неизменяемы'); END;
CREATE TRIGGER IF NOT EXISTS checklists_no_update BEFORE UPDATE ON checklists
  BEGIN SELECT RAISE(ABORT, 'версии чек-листа неизменяемы'); END;
CREATE TABLE IF NOT EXISTS employees (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('operator', 'qa', 'reviewer', 'manager', 'admin')),
  team TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor_id TEXT, actor_name TEXT NOT NULL,
  role TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
  details_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_at ON audit(at);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
  BEGIN SELECT RAISE(ABORT, 'журнал действий только дополняется'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'журнал действий только дополняется'); END;
"""

RunStatus = Literal["running", "done", "cancelled"]


@dataclass(frozen=True)
class RunRow:
    id: int
    total: int
    done: int
    cost: float
    calls: int
    errors: list[str]
    status: RunStatus
    started: float
    finished: float | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False)


def connect(path: str) -> sqlite3.Connection:
    """Открыть базу: WAL, внешние ключи, схема. Для файла создаёт родительскую папку."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


class Store:
    """Доступ к таблицам хранилища. Каждый метод записи фиксируется транзакцией."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- диалоги ---

    def add_dialogs(self, dialogs: Sequence[Dialog], audio: Mapping[str, str]) -> tuple[int, int]:
        """Сохранить новые диалоги, пропустить дубли по id. Возвращает (added, дубли)."""
        added = duplicates = 0
        with self._conn:
            for dialog in dialogs:
                exists = self._conn.execute("SELECT 1 FROM dialogs WHERE id = ?", (dialog.id,)).fetchone()
                if exists is not None:
                    duplicates += 1
                    continue
                body = dialog.model_dump(mode="json", exclude={"res", "reviewed", "cost"})
                self._conn.execute(
                    "INSERT INTO dialogs (id, body, audio_url) VALUES (?, ?, ?)",
                    (dialog.id, _dump(body), audio.get(dialog.id)),
                )
                added += 1
        return added, duplicates

    def audio_url(self, dialog_id: str) -> str | None:
        row = self._conn.execute("SELECT audio_url FROM dialogs WHERE id = ?", (dialog_id,)).fetchone()
        return row["audio_url"] if row is not None else None

    def prosody(self, dialog_id: str) -> dict[str, Any] | None:
        """Интонация звонка, посчитанная раньше (`GET /api/dialogs/{id}/prosody`)."""
        row = self._conn.execute("SELECT body FROM prosody WHERE dialog_id = ?", (dialog_id,)).fetchone()
        return json.loads(row["body"]) if row is not None else None

    def set_prosody(self, dialog_id: str, body: Mapping[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO prosody (dialog_id, body) VALUES (?, ?)", (dialog_id, _dump(body))
            )

    def set_cost(self, dialog_id: str, cost: Cost) -> None:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE dialogs SET cost = ? WHERE id = ?", (_dump(cost.model_dump()), dialog_id)
            )
            if cur.rowcount == 0:
                raise KeyError(dialog_id)

    def _dialog_from_row(self, row: sqlite3.Row) -> Dialog:
        data = json.loads(row["body"])
        data["res"] = {}
        data["reviewed"] = bool(row["reviewed"])
        if row["cost"] is not None:
            data["cost"] = json.loads(row["cost"])
        else:
            data["cost"] = None
        return Dialog.model_validate(data)

    def get_dialog(self, dialog_id: str) -> Dialog | None:
        row = self._conn.execute(
            "SELECT body, reviewed, cost FROM dialogs WHERE id = ?", (dialog_id,)
        ).fetchone()
        return self._dialog_from_row(row) if row is not None else None

    def list_dialogs(self) -> list[Dialog]:
        rows = self._conn.execute("SELECT body, reviewed, cost FROM dialogs ORDER BY rowid").fetchall()
        return [self._dialog_from_row(row) for row in rows]

    def set_reviewed(self, dialog_id: str, reviewed: bool) -> None:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE dialogs SET reviewed = ? WHERE id = ?", (int(reviewed), dialog_id)
            )
            if cur.rowcount == 0:
                raise KeyError(dialog_id)

    # --- чек-листы ---

    def add_checklist(self, checklist: Checklist, note: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO checklists (version, body, note, created) VALUES (?, ?, ?, ?)",
                (checklist.version, _dump(checklist.model_dump(mode="json")), note, _now()),
            )

    def current_checklist(self) -> Checklist | None:
        row = self._conn.execute("SELECT body FROM checklists ORDER BY version DESC LIMIT 1").fetchone()
        return Checklist.model_validate(json.loads(row["body"])) if row is not None else None

    def checklist(self, version: int) -> Checklist | None:
        row = self._conn.execute("SELECT body FROM checklists WHERE version = ?", (version,)).fetchone()
        return Checklist.model_validate(json.loads(row["body"])) if row is not None else None

    def list_versions(self) -> list[dict[str, object]]:
        rows = self._conn.execute("SELECT version, note FROM checklists ORDER BY version").fetchall()
        return [{"v": row["version"], "note": row["note"]} for row in rows]

    # --- результаты ---

    def add_result(self, dialog_id: str, cid: str, version: int, fp: str, result: CriterionResult) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO results (dialog_id, cid, version, fp, body, created) VALUES (?, ?, ?, ?, ?, ?)",
                (dialog_id, cid, version, fp, _dump(result.model_dump(mode="json")), _now()),
            )

    def current_results(self, fps: Mapping[str, str]) -> dict[str, dict[str, CriterionResult]]:
        """Для каждой пары — последний по id результат с отпечатком fps[cid]."""
        latest: dict[tuple[str, str], CriterionResult] = {}
        rows = self._conn.execute("SELECT id, dialog_id, cid, fp, body FROM results ORDER BY id").fetchall()
        for row in rows:
            fp = fps.get(row["cid"])
            if fp is None or row["fp"] != fp:
                continue
            latest[(row["dialog_id"], row["cid"])] = CriterionResult.model_validate(json.loads(row["body"]))
        out: dict[str, dict[str, CriterionResult]] = {}
        for (dialog_id, cid), result in latest.items():
            out.setdefault(dialog_id, {})[cid] = result
        return out

    # --- запуски ---

    def add_run(self, total: int, started: float) -> int:
        with self._conn:
            cur = self._conn.execute("INSERT INTO runs (total, started) VALUES (?, ?)", (total, started))
            if cur.lastrowid is None:
                raise RuntimeError("sqlite не вернул id запуска")
            return cur.lastrowid

    def record_progress(
        self, run_id: int, done: int, cost: float, calls: int, errors: Sequence[str] = ()
    ) -> None:
        with self._conn:
            row = self._conn.execute("SELECT errors FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            merged = json.loads(row["errors"]) + list(errors)
            self._conn.execute(
                "UPDATE runs SET done = done + ?, cost = cost + ?, calls = calls + ?, errors = ? "
                "WHERE id = ?",
                (done, cost, calls, _dump(merged), run_id),
            )

    def finish_run(self, run_id: int, finished: float, status: RunStatus) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE runs SET finished = ?, status = ? WHERE id = ?",
                (finished, status, run_id),
            )

    def cancel_stale_runs(self) -> None:
        with self._conn:
            self._conn.execute("UPDATE runs SET status = 'cancelled' WHERE status = 'running'")

    def get_run(self, run_id: int) -> RunRow | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRow(
            id=row["id"],
            total=row["total"],
            done=row["done"],
            cost=row["cost"],
            calls=row["calls"],
            errors=json.loads(row["errors"]),
            status=row["status"],
            started=row["started"],
            finished=row["finished"],
        )

    # --- апелляции и решения ---

    def add_appeal(self, appeal: Appeal, fp: str) -> Appeal:
        """Записать апелляцию или решение, присвоить id вида «a{n}»."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO appeals (dlg, cid, kind, fp, status, body) VALUES (?, ?, ?, ?, ?, ?)",
                (appeal.dlg, appeal.cid, appeal.kind, fp, appeal.status, "{}"),
            )
            if cur.lastrowid is None:
                raise RuntimeError("sqlite не вернул n апелляции")
            n = cur.lastrowid
            appeal = appeal.model_copy(update={"id": f"a{n}"})
            self._conn.execute(
                "UPDATE appeals SET body = ? WHERE n = ?",
                (_dump(appeal.model_dump(mode="json", by_alias=True)), n),
            )
        return appeal

    @staticmethod
    def _appeal_number(appeal_id: str) -> int | None:
        try:
            return int(appeal_id.removeprefix("a"))
        except ValueError:
            return None

    def get_appeal(self, appeal_id: str) -> tuple[Appeal, str] | None:
        n = self._appeal_number(appeal_id)
        if n is None:
            return None
        row = self._conn.execute("SELECT body, fp FROM appeals WHERE n = ?", (n,)).fetchone()
        if row is None:
            return None
        return Appeal.model_validate(json.loads(row["body"])), row["fp"]

    def save_decision(self, appeal: Appeal) -> None:
        n = self._appeal_number(appeal.id)
        if n is None:
            raise KeyError(appeal.id)
        with self._conn:
            self._conn.execute(
                "UPDATE appeals SET status = ?, body = ? WHERE n = ?",
                (appeal.status, _dump(appeal.model_dump(mode="json", by_alias=True)), n),
            )

    def close_pending_appeals(self, cids: Sequence[str]) -> list[str]:
        """Ожидающие апелляции этих критериев → closed. Возвращает их id."""
        if not cids:
            return []
        placeholders = ",".join("?" * len(cids))
        rows = self._conn.execute(
            f"SELECT n, body FROM appeals "  # noqa: S608
            f"WHERE kind = 'appeal' AND status = 'pending' AND cid IN ({placeholders})",
            tuple(cids),
        ).fetchall()
        closed: list[str] = []
        with self._conn:
            for row in rows:
                data = json.loads(row["body"])
                data["status"] = "closed"
                self._conn.execute(
                    "UPDATE appeals SET status = 'closed', body = ? WHERE n = ?",
                    (_dump(data), row["n"]),
                )
                closed.append(f"a{row['n']}")
        return closed

    def list_appeals(self) -> list[tuple[Appeal, str]]:
        rows = self._conn.execute("SELECT body, fp FROM appeals ORDER BY n").fetchall()
        return [(Appeal.model_validate(json.loads(row["body"])), row["fp"]) for row in rows]

    # --- адресаты причин ---

    def get_owners(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT tag, owner FROM owners").fetchall()
        return {row["tag"]: row["owner"] for row in rows}

    def overrides(self) -> dict[str, Any]:
        """Значения `Settings`, сохранённые из интерфейса: имя поля -> значение JSON."""
        return {
            r["key"]: json.loads(r["value"]) for r in self._conn.execute("SELECT key, value FROM overrides")
        }

    def set_overrides(self, values: Mapping[str, Any]) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO overrides (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(k, _dump(v)) for k, v in values.items()],
            )

    def org_source(self) -> tuple[str, str] | None:
        """Ссылка API организаторов и group_id автосинхронизации, сохранённые из интерфейса."""
        row = self._conn.execute("SELECT url, group_id FROM org_source").fetchone()
        return (row["url"], row["group_id"]) if row else None

    def set_org_source(self, url: str, group_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO org_source (id, url, group_id) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET url = excluded.url, group_id = excluded.group_id",
                (url, group_id),
            )

    def set_owners(self, owners: Mapping[str, str]) -> None:
        with self._conn:
            for tag, owner in owners.items():
                self._conn.execute(
                    "INSERT INTO owners (tag, owner) VALUES (?, ?) "
                    "ON CONFLICT(tag) DO UPDATE SET owner = excluded.owner",
                    (tag, owner),
                )

    # --- сотрудники и журнал действий ---

    @staticmethod
    def _employee(row: sqlite3.Row) -> dict[str, Any]:
        return {**dict(row), "active": bool(row["active"])}

    def employees(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM employees ORDER BY name, id").fetchall()
        return [self._employee(row) for row in rows]

    def employee(self, employee_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return self._employee(row) if row is not None else None

    def put_employees(self, employees: Sequence[Mapping[str, Any]]) -> None:
        """Добавить или заменить сотрудников одной транзакцией: `{id, name, role, team, active}`."""
        with self._conn:
            self._conn.executemany(
                "INSERT INTO employees (id, name, role, team, active) "
                "VALUES (:id, :name, :role, :team, :active) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, role = excluded.role, "
                "team = excluded.team, active = excluded.active",
                employees,
            )

    def add_audit(self, entry: Mapping[str, Any]) -> None:
        """Строка журнала: at, actor_id, actor_name, role, action, target_type, target_id, details."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO audit (at, actor_id, actor_name, role, action, target_type, target_id, "
                "details_json) VALUES (:at, :actor_id, :actor_name, :role, :action, :target_type, "
                ":target_id, :details_json)",
                {**entry, "details_json": _dump(entry["details"])},
            )

    def audit(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Новые первыми. `actor` — id сотрудника или подпись без входа, `since` — начало ISO-даты."""
        rows = self._conn.execute(
            "SELECT * FROM audit WHERE (:actor IS NULL OR actor_id = :actor OR actor_name = :actor) "
            "AND (:action IS NULL OR action = :action) AND (:since IS NULL OR at >= :since) "
            "ORDER BY id DESC LIMIT :limit",
            {"actor": actor, "action": action, "since": since, "limit": -1 if limit is None else limit},
        ).fetchall()
        out = [dict(row) for row in rows]
        for entry in out:
            entry["details"] = json.loads(entry.pop("details_json"))
        return out

    def audit_counts(self, since: str | None = None) -> list[tuple[str | None, str, int]]:
        """(actor_id, action, сколько) с `since`; actor_id None — действия без входа."""
        rows = self._conn.execute(
            "SELECT actor_id, action, COUNT(*) AS n FROM audit WHERE (:since IS NULL OR at >= :since) "
            "GROUP BY actor_id, action",
            {"since": since},
        ).fetchall()
        return [(row["actor_id"], row["action"], row["n"]) for row in rows]

    # --- автоматизация ---

    def automation(self, key: str) -> Any:
        """Сохранённое значение автоматизации: `settings` (JSON настроек), `paused` (bool); None — нет."""
        row = self._conn.execute("SELECT value FROM automation WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_automation(self, key: str, value: Any) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO automation (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, _dump(value)),
            )

    def add_cycle(self, cycle: Mapping[str, Any]) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO automation_cycles (started, body) VALUES (?, ?)",
                (cycle["started"], _dump(cycle)),
            )
            if cur.lastrowid is None:
                raise RuntimeError("sqlite не вернул id цикла")
            return cur.lastrowid

    def cycles(self, *, limit: int | None = None, since: str | None = None) -> list[dict[str, Any]]:
        """Циклы автоматизации новыми первыми; `since` — ISO-время начала (все в одном поясе)."""
        rows = self._conn.execute(
            "SELECT id, body FROM automation_cycles WHERE started >= ? ORDER BY id DESC LIMIT ?",
            (since or "", -1 if limit is None else limit),
        ).fetchall()
        return [{**json.loads(r["body"]), "id": r["id"]} for r in rows]
