"""Хранилище SQLite: один файл, режим WAL, неизменяемые версии и результаты."""

import sqlite3
from pathlib import Path

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
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
  BEGIN SELECT RAISE(ABORT, 'результаты неизменяемы'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
  BEGIN SELECT RAISE(ABORT, 'результаты неизменяемы'); END;
CREATE TRIGGER IF NOT EXISTS checklists_no_update BEFORE UPDATE ON checklists
  BEGIN SELECT RAISE(ABORT, 'версии чек-листа неизменяемы'); END;
"""


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
