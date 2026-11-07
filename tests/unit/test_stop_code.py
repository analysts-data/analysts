"""scripts/stop_code.sh: после 2026-11-08T12:00:00+05:00 ветка не отличается от origin/main.

CQA_NOW задаёт время изнутри теста (в Settings его нет, design/ports.md).
"""

from __future__ import annotations

from pathlib import Path

from gitrepo import REPO_ROOT, clone_with_origin, commit_all, run_script

BEFORE = "2026-11-08T11:44:00+05:00"
AFTER = "2026-11-08T12:01:00+05:00"
STOP = "стоп-код 12:00, код не меняется"


def test_commit_before_deadline_passes(tmp_path: Path) -> None:
    repo = clone_with_origin(tmp_path)
    (repo / "fix.txt").write_text("последние правки\n", encoding="utf-8")
    commit_all(repo, "fix")

    result = run_script("stop_code.sh", cwd=repo, CQA_NOW=BEFORE)

    assert result.returncode == 0, result.stdout + result.stderr


def test_commit_after_deadline_fails(tmp_path: Path) -> None:
    repo = clone_with_origin(tmp_path)
    (repo / "fix.txt").write_text("правка после стоп-кода\n", encoding="utf-8")
    commit_all(repo, "late fix")

    result = run_script("stop_code.sh", cwd=repo, CQA_NOW=AFTER)

    assert result.returncode != 0
    assert STOP in result.stdout + result.stderr


def test_branch_equal_to_origin_passes_after_deadline(tmp_path: Path) -> None:
    repo = clone_with_origin(tmp_path)  # feat/test без коммитов поверх origin/main

    result = run_script("stop_code.sh", cwd=repo, CQA_NOW=AFTER)

    assert result.returncode == 0, result.stdout + result.stderr


def test_make_check_runs_stop_code() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    check_target = makefile.split("check:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/stop_code.sh" in check_target
