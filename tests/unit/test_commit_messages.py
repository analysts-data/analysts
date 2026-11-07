"""scripts/commit_messages.sh: сообщения коммитов ветки без следов ИИ-соавторства."""

from __future__ import annotations

from pathlib import Path

import pytest
from gitrepo import clone_with_origin, commit_all, git, init_repo, run_script

BAD_TRAILERS = [
    "Co-Authored-By: Someone <someone@example.com>",
    "co-authored-by: someone",
    "Generated with Foo CLI",
    "generated with something",
]


def branch_with_commit(tmp_path: Path, message: str) -> Path:
    repo = clone_with_origin(tmp_path)
    (repo / "change.txt").write_text("x\n", encoding="utf-8")
    commit_all(repo, "подготовка")
    (repo / "change.txt").write_text("y\n", encoding="utf-8")
    git("commit", "-am", message, cwd=repo)
    return repo


def test_clean_history_passes(tmp_path: Path) -> None:
    repo = branch_with_commit(tmp_path, "feat(core): обычное сообщение")

    result = run_script("commit_messages.sh", cwd=repo)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("trailer", BAD_TRAILERS)
def test_forbidden_trailer_fails(tmp_path: Path, trailer: str) -> None:
    repo = branch_with_commit(tmp_path, f"feat(core): сообщение\n\n{trailer}\n")

    result = run_script("commit_messages.sh", cwd=repo)

    assert result.returncode != 0
    assert "feat(core): сообщение" in result.stderr


def test_base_commits_are_not_checked(tmp_path: Path) -> None:
    seed = init_repo(tmp_path / "seed")
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "base")
    (seed / "legacy.txt").write_text("x\n", encoding="utf-8")
    git("add", "legacy.txt", cwd=seed)
    git("commit", "-m", "legacy\n\nCo-Authored-By: Old <old@example.com>\n", cwd=seed)
    git("clone", "--bare", str(seed), str(tmp_path / "origin.git"), cwd=tmp_path)
    repo = tmp_path / "clone"
    git("clone", str(tmp_path / "origin.git"), str(repo), cwd=tmp_path)
    git("switch", "-c", "feat/test", cwd=repo)
    (repo / "new.txt").write_text("y\n", encoding="utf-8")
    commit_all(repo, "чистый коммит")

    result = run_script("commit_messages.sh", cwd=repo)

    assert result.returncode == 0, result.stderr


def test_missing_base_warns_and_passes(tmp_path: Path) -> None:
    repo = branch_with_commit(tmp_path, "feat(core): сообщение")

    result = run_script("commit_messages.sh", "--base", "origin/nothing", cwd=repo)

    assert result.returncode == 0
    assert "origin/nothing" in result.stderr
