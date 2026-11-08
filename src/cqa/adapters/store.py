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
CREATE TABLE IF NOT EXISTS run_dialogs (
  run_id INTEGER NOT NULL REFERENCES runs(id), dialog_id TEXT NOT NULL REFERENCES dialogs(id),
  status TEXT NOT NULL
    CHECK (status IN ('queued', 'evaluating', 'done', 'error', 'skipped', 'cancelled')),
  total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0, error TEXT,
  PRIMARY KEY (run_id, dialog_id));
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
CREATE TABLE IF NOT EXISTS markers (
  dialog_id TEXT NOT NULL REFERENCES dialogs(id), label TEXT NOT NULL, by TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY (dialog_id, label));
CREATE TABLE IF NOT EXISTS lists (name TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')), title TEXT NOT NULL,
  target_type TEXT NOT NULL, target_id TEXT NOT NULL, basis TEXT NOT NULL, created TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'ack', 'resolved')),
  assignee TEXT, acked_by TEXT, acked_at TEXT, resolved_by TEXT, resolved_at TEXT, note TEXT,
  UNIQUE (rule_id, target_type, target_id));
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, role TEXT,
  event TEXT NOT NULL, page TEXT NOT NULL, props TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS telemetry_at ON telemetry(at);
CREATE TRIGGER IF NOT EXISTS telemetry_no_update BEFORE UPDATE ON telemetry
  BEGIN SELECT RAISE(ABORT, 'метрики только дописываются'); END;
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

# Колонки, добавленные после первых баз: connect досоздаёт их в старой базе, прежние строки получают умолчание
COLUMNS = [
    ("dialogs", "operator", "TEXT"),  # сотрудник диалога (data/demo.db, data/cqa.db до колонки)
    ("results", "run_id", "INTEGER"),  # запуск, давший ответ; NULL — ручной ответ или строка до колонки
    ("runs", "model", "TEXT"),
    ("runs", "checklist_version", "INTEGER"),
    ("runs", "force", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "skipped", "INTEGER NOT NULL DEFAULT 0"),
    ("runs", "apply", "TEXT NOT NULL DEFAULT 'replace'"),  # compare — ответы теневые, итог не меняют
    ("runs", "override", "TEXT"),  # JSON настроек перепроверки поверх режима; NULL — режим как есть
    ("results", "shadow", "INTEGER NOT NULL DEFAULT 0"),  # теневой ответ запуска compare: не текущий
]

RunStatus = Literal["running", "done", "cancelled"]
DialogStatus = Literal["queued", "evaluating", "done", "error", "skipped", "cancelled"]


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
    model: str | None
    checklist_version: int | None
    force: bool
    skipped: int
    apply: str
    override: dict[str, Any] | None


@dataclass(frozen=True)
class ResultRow:
    id: int
    dialog_id: str
    cid: str
    version: int
    fp: str
    created: str
    run_id: int | None
    result: CriterionResult
    shadow: bool


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
    for table, column, decl in COLUMNS:
        if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.row_factory = sqlite3.Row
    return conn


class Store:
    """Доступ к таблицам хранилища. Каждый метод записи фиксируется транзакцией."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- диалоги ---

    def add_dialogs(self, dialogs: Sequence[Dialog], audio: Mapping[str, str]) -> tuple[int, int]:
        """Сохранить новые диалоги, пропустить дубли по id. Возвращает (added, дубли).

        У дубля дописывается только сотрудник, если его ещё нет: назначенного вручную повтор не меняет.
        """
        added = duplicates = 0
        with self._conn:
            for dialog in dialogs:
                exists = self._conn.execute("SELECT 1 FROM dialogs WHERE id = ?", (dialog.id,)).fetchone()
                if exists is not None:
                    duplicates += 1
                    self._conn.execute(
                        "UPDATE dialogs SET operator = ? WHERE id = ? AND operator IS NULL",
                        (dialog.operator, dialog.id),
                    )
                    continue
                body = dialog.model_dump(mode="json", exclude={"res", "reviewed", "cost", "operator"})
                self._conn.execute(
                    "INSERT INTO dialogs (id, body, audio_url, operator) VALUES (?, ?, ?, ?)",
                    (dialog.id, _dump(body), audio.get(dialog.id), dialog.operator),
                )
                added += 1
        return added, duplicates

    def set_operator(self, dialog_id: str, operator: str | None) -> None:
        with self._conn:
            cur = self._conn.execute("UPDATE dialogs SET operator = ? WHERE id = ?", (operator, dialog_id))
            if cur.rowcount == 0:
                raise KeyError(dialog_id)

    def set_operators(self, pairs: Sequence[tuple[str, str | None]]) -> tuple[int, list[str]]:
        """Назначить сотрудников одной транзакцией. Возвращает (обновлено, неизвестные id по порядку)."""
        updated, unknown = 0, []
        with self._conn:
            for dialog_id, operator in pairs:
                cur = self._conn.execute(
                    "UPDATE dialogs SET operator = ? WHERE id = ?", (operator, dialog_id)
                )
                if cur.rowcount:
                    updated += 1
                else:
                    unknown.append(dialog_id)
        return updated, unknown

    def audio_url(self, dialog_id: str) -> str | None:
        row = self._conn.execute("SELECT audio_url FROM dialogs WHERE id = ?", (dialog_id,)).fetchone()
        return row["audio_url"] if row is not None else None

    def prosody(self, dialog_id: str) -> dict[str, Any] | None:
        """Интонация звонка, посчитанная раньше (`GET /api/dialogs/{id}/prosody`)."""
        row = self._conn.execute("SELECT body FROM prosody WHERE dialog_id = ?", (dialog_id,)).fetchone()
        return json.loads(row["body"]) if row is not None else None

    def prosodies(self) -> dict[str, dict[str, Any]]:
        """Все сохранённые разборы интонации по id звонка: нормы статистики разговора."""
        rows = self._conn.execute("SELECT dialog_id, body FROM prosody ORDER BY rowid")
        return {r["dialog_id"]: json.loads(r["body"]) for r in rows}

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
        data["operator"] = row["operator"]
        if row["cost"] is not None:
            data["cost"] = json.loads(row["cost"])
        else:
            data["cost"] = None
        return Dialog.model_validate(data)

    def get_dialog(self, dialog_id: str) -> Dialog | None:
        row = self._conn.execute(
            "SELECT body, reviewed, cost, operator FROM dialogs WHERE id = ?", (dialog_id,)
        ).fetchone()
        return self._dialog_from_row(row) if row is not None else None

    def list_dialogs(self) -> list[Dialog]:
        rows = self._conn.execute(
            "SELECT body, reviewed, cost, operator FROM dialogs ORDER BY rowid"
        ).fetchall()
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

    def add_result(
        self,
        dialog_id: str,
        cid: str,
        version: int,
        fp: str,
        result: CriterionResult,
        run_id: int | None = None,
        shadow: bool = False,
    ) -> None:
        body = _dump(result.model_dump(mode="json"))
        with self._conn:
            self._conn.execute(
                "INSERT INTO results (dialog_id, cid, version, fp, body, created, run_id, shadow) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (dialog_id, cid, version, fp, body, _now(), run_id, int(shadow)),
            )

    @staticmethod
    def _result_row(row: sqlite3.Row) -> ResultRow:
        return ResultRow(
            id=row["id"],
            dialog_id=row["dialog_id"],
            cid=row["cid"],
            version=row["version"],
            fp=row["fp"],
            created=row["created"],
            run_id=row["run_id"],
            result=CriterionResult.model_validate(json.loads(row["body"])),
            shadow=bool(row["shadow"]),
        )

    def result_rows(self, *, dialog_id: str | None = None, run_id: int | None = None) -> list[ResultRow]:
        """Все строки результатов диалога или запуска по возрастанию id (история append-only)."""
        rows = self._conn.execute(
            "SELECT * FROM results WHERE (? IS NULL OR dialog_id = ?) AND (? IS NULL OR run_id = ?) "
            "ORDER BY id",
            (dialog_id, dialog_id, run_id, run_id),
        ).fetchall()
        return [self._result_row(row) for row in rows]

    def get_result(self, result_id: int) -> ResultRow | None:
        row = self._conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
        return self._result_row(row) if row is not None else None

    def current_results(self, fps: Mapping[str, str]) -> dict[str, dict[str, CriterionResult]]:
        """Для каждой пары — последний по id результат с отпечатком fps[cid]; теневые не в счёт."""
        latest: dict[tuple[str, str], CriterionResult] = {}
        rows = self._conn.execute(
            "SELECT id, dialog_id, cid, fp, body FROM results WHERE shadow = 0 ORDER BY id"
        ).fetchall()
        for row in rows:
            fp = fps.get(row["cid"])
            if fp is None or row["fp"] != fp:
                continue
            latest[(row["dialog_id"], row["cid"])] = CriterionResult.model_validate(json.loads(row["body"]))
        out: dict[str, dict[str, CriterionResult]] = {}
        for (dialog_id, cid), result in latest.items():
            out.setdefault(dialog_id, {})[cid] = result
        return out

    def results_between(self, start: float, end: float) -> list[tuple[str, int, CriterionResult]]:
        """(cid, версия чек-листа, результат), записанные в [start, end] (секунды эпохи), по порядку.

        ponytail: у результата нет run_id, запуск находится по времени; колонка run_id, если окна мало.
        """
        rows = self._conn.execute("SELECT cid, version, body, created FROM results ORDER BY id").fetchall()
        return [
            (row["cid"], row["version"], CriterionResult.model_validate(json.loads(row["body"])))
            for row in rows
            if start <= datetime.fromisoformat(row["created"]).timestamp() <= end
        ]

    # --- запуски ---

    def add_run(
        self,
        total: int,
        started: float,
        *,
        model: str | None = None,
        checklist_version: int | None = None,
        force: bool = False,
        skipped: int = 0,
        apply: str = "replace",
        override: Mapping[str, Any] | None = None,
    ) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO runs (total, started, model, checklist_version, force, skipped, apply, "
                "override) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    total,
                    started,
                    model,
                    checklist_version,
                    int(force),
                    skipped,
                    apply,
                    None if override is None else _dump(override),
                ),
            )
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
            if status == "cancelled":
                self._cancel_dialogs("run_id = ?", (run_id,))

    def cancel_stale_runs(self) -> None:
        with self._conn:
            self._cancel_dialogs("run_id IN (SELECT id FROM runs WHERE status = 'running')", ())
            self._conn.execute("UPDATE runs SET status = 'cancelled' WHERE status = 'running'")

    def _cancel_dialogs(self, where: str, args: tuple[object, ...]) -> None:
        """Диалоги, которые так и не оценились, — cancelled. Вызывать внутри транзакции."""
        self._conn.execute(
            f"UPDATE run_dialogs SET status = 'cancelled' "  # noqa: S608 — where из кода, не от клиента
            f"WHERE status IN ('queued', 'evaluating') AND {where}",
            args,
        )

    # --- статусы диалогов запуска ---

    def queue_dialogs(self, run_id: int, rows: Sequence[tuple[str, DialogStatus, int, int]]) -> None:
        """Диалоги запуска в порядке очереди: (id, статус, критериев к оценке, пар держит человек)."""
        with self._conn:
            self._conn.executemany(
                "INSERT INTO run_dialogs (run_id, dialog_id, status, total, skipped) VALUES (?, ?, ?, ?, ?)",
                [(run_id, *row) for row in rows],
            )

    def set_dialog_status(
        self, run_id: int, dialog_id: str, status: DialogStatus, *, done: int = 0, error: str | None = None
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE run_dialogs SET status = ?, done = ?, error = ? WHERE run_id = ? AND dialog_id = ?",
                (status, done, error, run_id, dialog_id),
            )

    @staticmethod
    def _dialog_status(row: sqlite3.Row) -> dict[str, Any]:
        return {k: row[k] for k in ("status", "error", "done", "total", "skipped")}

    def run_dialogs(self, run_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM run_dialogs WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [{"id": row["dialog_id"], **self._dialog_status(row)} for row in rows]

    def latest_dialog_status(self) -> dict[str, dict[str, Any]]:
        """Диалог → статус в последнем запуске, где он был, с `run_id`."""
        rows = self._conn.execute("SELECT * FROM run_dialogs ORDER BY run_id").fetchall()
        return {row["dialog_id"]: {"run_id": row["run_id"], **self._dialog_status(row)} for row in rows}

    @staticmethod
    def _run_row(row: sqlite3.Row) -> RunRow:
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
            model=row["model"],
            checklist_version=row["checklist_version"],
            force=bool(row["force"]),
            skipped=row["skipped"],
            apply=row["apply"],
            override=None if row["override"] is None else json.loads(row["override"]),
        )

    def get_run(self, run_id: int) -> RunRow | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_row(row) if row is not None else None

    def list_runs(self, limit: int = 50) -> list[RunRow]:
        """Последние запуски, новые первыми."""
        rows = self._conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._run_row(row) for row in rows]

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

    # --- маркеры, списки (каталог маркеров, правила алертов), алерты ---

    def markers(self) -> dict[str, list[dict[str, str]]]:
        """Ручные маркеры: id диалога -> [{label, by, at}] в порядке постановки."""
        out: dict[str, list[dict[str, str]]] = {}
        for r in self._conn.execute("SELECT dialog_id, label, by, at FROM markers ORDER BY rowid"):
            out.setdefault(r["dialog_id"], []).append({"label": r["label"], "by": r["by"], "at": r["at"]})
        return out

    def change_markers(
        self, dialog_id: str, add: Sequence[str], remove: Sequence[str], by: str, at: str
    ) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO markers (dialog_id, label, by, at) VALUES (?, ?, ?, ?)",
                [(dialog_id, label, by, at) for label in add],
            )
            self._conn.executemany(
                "DELETE FROM markers WHERE dialog_id = ? AND label = ?",
                [(dialog_id, label) for label in remove],
            )

    def get_list(self, name: str) -> Any:
        row = self._conn.execute("SELECT body FROM lists WHERE name = ?", (name,)).fetchone()
        return json.loads(row["body"]) if row is not None else None

    def set_list(self, name: str, body: object) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO lists (name, body) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET body = excluded.body",
                (name, _dump(body)),
            )

    def all_prosody(self) -> dict[str, dict[str, Any]]:
        return {r["dialog_id"]: json.loads(r["body"]) for r in self._conn.execute("SELECT * FROM prosody")}

    @staticmethod
    def _alert(row: sqlite3.Row) -> dict[str, Any]:
        return {**dict(row), "basis": json.loads(row["basis"])}

    def add_alerts(self, hits: Sequence[Mapping[str, Any]], created: str) -> list[dict[str, Any]]:
        """Новые алерты; пара (правило, цель), уже бывшая в таблице в любом статусе, пропускается."""
        ids = []
        with self._conn:
            for h in hits:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO alerts "
                    "(rule_id, severity, title, target_type, target_id, basis, created) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        h["rule_id"],
                        h["severity"],
                        h["title"],
                        h["target_type"],
                        h["target_id"],
                        _dump(h["basis"]),
                        created,
                    ),
                )
                if cur.rowcount:
                    ids.append(cur.lastrowid)
        return [a for i in ids if (a := self.get_alert(i)) is not None]

    def get_alert(self, alert_id: int | None) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return self._alert(row) if row is not None else None

    def list_alerts(self) -> list[dict[str, Any]]:
        return [self._alert(r) for r in self._conn.execute("SELECT * FROM alerts ORDER BY id DESC")]

    ALERT_FIELDS = frozenset(
        {"status", "assignee", "acked_by", "acked_at", "resolved_by", "resolved_at", "note"}
    )

    def update_alert(self, alert_id: int, **fields: str | None) -> None:
        assert set(fields) <= self.ALERT_FIELDS, fields
        with self._conn:
            self._conn.execute(
                f"UPDATE alerts SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",  # noqa: S608
                (*fields.values(), alert_id),
            )

    # --- метрики использования (только дописываются, старше срока хранения удаляются при старте) ---

    def add_telemetry(self, rows: Sequence[tuple[str, str, str | None, str, str, str]]) -> None:
        """rows — (at ISO UTC, actor, role, event, page, props JSON)."""
        with self._conn:
            self._conn.executemany(
                "INSERT INTO telemetry (at, actor, role, event, page, props) VALUES (?, ?, ?, ?, ?, ?)", rows
            )

    def telemetry(
        self, after: str | None, role: str | None
    ) -> list[tuple[str, str, str | None, str, str, str]]:
        rows = self._conn.execute(
            "SELECT at, actor, role, event, page, props FROM telemetry "
            "WHERE (? IS NULL OR at >= ?) AND (? IS NULL OR role = ?) ORDER BY id",
            (after, after, role, role),
        ).fetchall()
        return [(r["at"], r["actor"], r["role"], r["event"], r["page"], r["props"]) for r in rows]

    def purge_telemetry(self, before: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM telemetry WHERE at < ?", (before,))

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
