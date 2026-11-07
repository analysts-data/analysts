"""make backup: согласованная копия базы через sqlite3.Connection.backup.

Диалоги попадают в базу через HTTP (POST /api/datasets/upload), апелляция — через
Store: маршрут /api/appeals пишет другая группа, здесь важна сама копия.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from cqa.adapters.store import Store, connect
from cqa.domain.models import Appeal
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource, prototype_checklist, prototype_dialogs

REPO_ROOT = Path(__file__).resolve().parents[2]


def _client(db_path: Path, dialogs: list) -> tuple[TestClient, FakeEvaluator]:
    evaluator = FakeEvaluator()
    settings = Settings(_env_file=None, db_path=str(db_path))
    app = create_app(settings, source=FakeSource(dialogs), evaluator=evaluator)
    return TestClient(app), evaluator


def _add_appeal(db_path: Path, dlg_id: str) -> None:
    """Одна апелляция в ожидании: пары «диалог, критерий» с решением нет."""
    checklist = prototype_checklist()
    scale = next(c for c in checklist.criteria if c.type == "scale")
    conn = connect(db_path)
    appeal = Appeal(
        id="",
        kind="appeal",
        dlg=dlg_id,
        cid=scale.id,
        **{"from": scale.steps[-1], "ask": scale.steps[-2]},
        by="Оператор",
        at="07.11 15:10",
        status="pending",
        comment="Итог подведён.",
    )
    Store(conn).add_appeal(appeal, "fp-seed")
    conn.close()


def test_backup_copy_serves_the_same_state(tmp_path: Path) -> None:
    db_path = tmp_path / "cqa.db"
    dialogs = prototype_dialogs()
    client, evaluator = _client(db_path, dialogs)
    assert client.post("/api/datasets/upload", content=b"{}").json() == {
        "added": len(dialogs),
        "skipped": 0,
    }
    _add_appeal(db_path, dialogs[0].id)
    original = client.get("/api/state").json()
    assert original["dialogs"] and original["appeals"]

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "backup_db.py")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "CQA_DB_PATH": str(db_path)},
    )

    assert result.returncode == 0, result.stderr
    backup = Path(result.stdout.strip().splitlines()[-1])
    assert backup.exists()
    assert backup != db_path

    copy_client, copy_evaluator = _client(backup, dialogs)
    copied = copy_client.get("/api/state").json()

    assert copied["dialogs"] == original["dialogs"]
    assert copied["appeals"] == original["appeals"]
    assert copy_evaluator.calls == 0  # состояние копии без вызовов модели


def test_backup_reports_missing_database(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "backup_db.py")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "CQA_DB_PATH": str(tmp_path / "nope.db")},
    )

    assert result.returncode != 0
    assert "nope.db" in result.stderr


def test_make_backup_runs_the_script() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("backup:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/backup_db.py" in target
