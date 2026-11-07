"""scripts/protected_paths.sh: защищённые пути и файлы агентов вне git."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from gitrepo import clone_with_origin, commit_all, run_script

PROTECTED = [
    "eval/gold/case1.json",
    "eval/thresholds.yaml",
    "eval/baseline.json",
    "design/contract.md",
    "design/ports.md",
    ".github/workflows/check.yml",
]

AGENT_FILES = [
    "openspec/proposal.md",
    ".claude/settings.json",
    ".pi/skills/x/SKILL.md",
    "AGENTS.md",
    "AGENT.md",
    "CLAUDE.md",
]


def changed_repo(tmp_path: Path, filename: str) -> Path:
    repo = clone_with_origin(tmp_path)
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("изменение\n", encoding="utf-8")
    commit_all(repo, "edit")
    return repo


def test_clean_branch_passes_in_ci(tmp_path: Path) -> None:
    repo = clone_with_origin(tmp_path)

    result = run_script("protected_paths.sh", cwd=repo, GITHUB_ACTIONS="true")

    assert result.returncode == 0, result.stderr


def test_nonprotected_change_passes_in_ci(tmp_path: Path) -> None:
    repo = changed_repo(tmp_path, "src/cqa/new_module.py")

    result = run_script("protected_paths.sh", cwd=repo, GITHUB_ACTIONS="true")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("filename", PROTECTED)
def test_protected_change_fails_in_ci(tmp_path: Path, filename: str) -> None:
    repo = changed_repo(tmp_path, filename)

    result = run_script("protected_paths.sh", cwd=repo, GITHUB_ACTIONS="true")

    assert result.returncode != 0
    assert filename in result.stderr


@pytest.mark.parametrize("flag", ["--allow", "PROTECTED_ALLOW"])
def test_protected_change_allowed_with_human_ok(tmp_path: Path, flag: str) -> None:
    repo = changed_repo(tmp_path, "eval/thresholds.yaml")

    if flag == "--allow":
        result = run_script("protected_paths.sh", "--allow", cwd=repo, GITHUB_ACTIONS="true")
    else:
        result = run_script("protected_paths.sh", cwd=repo, GITHUB_ACTIONS="true", PROTECTED_ALLOW="1")

    assert result.returncode == 0, result.stderr


def test_protected_change_warns_locally(tmp_path: Path) -> None:
    repo = changed_repo(tmp_path, "design/ports.md")

    result = run_script("protected_paths.sh", cwd=repo)

    assert result.returncode == 0
    assert "design/ports.md" in result.stderr
    assert "human-ok" in result.stderr


@pytest.mark.parametrize("filename", AGENT_FILES)
def test_tracked_agent_file_fails(tmp_path: Path, filename: str) -> None:
    repo = changed_repo(tmp_path, filename)

    result = run_script("protected_paths.sh", cwd=repo)

    assert result.returncode != 0
    assert filename in result.stderr


def test_tracked_agent_file_fails_even_with_allow(tmp_path: Path) -> None:
    repo = changed_repo(tmp_path, "AGENTS.md")

    result = run_script("protected_paths.sh", "--allow", cwd=repo)

    assert result.returncode != 0


def test_tracked_agent_symlink_fails(tmp_path: Path) -> None:
    repo = clone_with_origin(tmp_path)
    os.symlink(str(tmp_path / "shared"), repo / "openspec")
    commit_all(repo, "add symlink")

    result = run_script("protected_paths.sh", cwd=repo)

    assert result.returncode != 0
    assert "openspec" in result.stderr


def test_missing_base_warns_and_passes(tmp_path: Path) -> None:
    repo = clone_with_origin(tmp_path)

    result = run_script("protected_paths.sh", "--base", "origin/nothing", cwd=repo)

    assert result.returncode == 0
    assert "origin/nothing" in result.stderr
