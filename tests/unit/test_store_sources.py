"""Реестр источников в хранилище: встроенные источники, перенос прежней ссылки, дубли, журнал."""

import sqlite3
from pathlib import Path

from cqa.adapters.store import Store, connect
from cqa.domain.models import Dialog

URL = "https://org.test/api/dialogs?group_id=DEV&token=t"


def _dialog(id_: str, source_id: str | None = None, external_id: str | None = None) -> Dialog:
    return Dialog(id=id_, ch="chat", lang="RU", at="", lines=[], source_id=source_id, external_id=external_id)


def test_new_base_has_the_builtin_sources_and_a_disabled_org_api() -> None:
    sources = {s["id"]: s for s in Store(connect(":memory:")).sources()}
    assert {k: v["kind"] for k, v in sources.items()} == {
        "org": "org_api",
        "file": "file",
        "paste": "paste",
        "api": "api",
    }
    assert sources["org"]["enabled"] is False and sources["org"]["secret"] is None


def test_the_old_saved_link_and_old_dialogs_move_into_the_registry(tmp_path: Path) -> None:
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE dialogs (id TEXT PRIMARY KEY, body TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,"
        " audio_url TEXT, cost TEXT);"
        "CREATE TABLE org_source (id INTEGER PRIMARY KEY CHECK (id = 1), url TEXT NOT NULL,"
        " group_id TEXT NOT NULL);"
        f"INSERT INTO org_source VALUES (1, '{URL}', 'DEV');"
        """INSERT INTO dialogs (id, body) VALUES ('p1-ru-001', '{"id": "p1-ru-001", "ch": "chat",
           "lang": "RU", "at": "", "lines": []}'), ('paste-1', '{"id": "paste-1", "ch": "chat",
           "lang": "RU", "at": "", "lines": []}');"""
    )
    old.commit()
    old.close()
    store = Store(connect(path))
    org = store.source("org")
    assert org is not None
    assert (org["secret"], org["config"], org["enabled"]) == (URL, {"group_id": "DEV"}, True)
    assert store.org_source() == (URL, "DEV")
    assert {d.id: d.source_id for d in store.list_dialogs()} == {"p1-ru-001": "org", "paste-1": "paste"}
    Store(connect(path))  # второй запуск ничего не ломает


def test_dialogs_are_deduplicated_by_source_and_external_id() -> None:
    store = Store(connect(":memory:"))
    assert store.add_dialogs([_dialog("s1-7", "s1", "7"), _dialog("s2-7", "s2", "7")], {}) == (2, 0)
    assert store.add_dialogs([_dialog("s1-7-again", "s1", "7")], {}) == (0, 1)
    got = store.get_dialog("s1-7")
    assert got is not None and (got.source_id, got.external_id) == ("s1", "7")
    assert store.source_dialogs()["s1"][0] == 1


def test_sync_log_keeps_status_counts_and_errors_newest_first() -> None:
    store = Store(connect(":memory:"))
    first = store.start_sync("file")
    store.finish_sync(first, "partial", 3, 1, ["x: нет текста"], 12)
    second = store.start_sync("file")
    rows = store.syncs("file")
    assert [r["id"] for r in rows] == [second, first]
    assert rows[0]["status"] == "running"
    assert (rows[1]["status"], rows[1]["added"], rows[1]["errors"], rows[1]["duration_ms"]) == (
        "partial",
        3,
        ["x: нет текста"],
        12,
    )
    store.fail_stale_syncs()
    assert store.syncs("file")[0]["errors"] == ["прервана перезапуском сервера"]
