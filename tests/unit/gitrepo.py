"""Общие помощники для тестов bash-скриптов scripts/: временные git-репозитории.

Важно: строки с сигнатурами секретов собираются из частей, чтобы репозиторий
сам не содержал их дословно (scripts/secret_scan.sh ищет их в трекаемых файлах).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

_DROPPED = {"GITHUB_ACTIONS", "PROTECTED_ALLOW"}


def base_env(**overrides: str) -> dict[str, str]:
    """Изолированное окружение для git: без глобальных конфигов и переменных CI."""
    env = {k: v for k, v in os.environ.items() if k not in _DROPPED}
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test Agent",
        GIT_AUTHOR_EMAIL="agent@example.com",
        GIT_COMMITTER_NAME="Test Agent",
        GIT_COMMITTER_EMAIL="agent@example.com",
    )
    env.update(overrides)
    return env


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True, env=base_env()
    )


def init_repo(path: Path) -> Path:
    """Пустой репозиторий с веткой main."""
    path.mkdir(parents=True, exist_ok=True)
    git("-c", "init.defaultBranch=main", "init", cwd=path)
    return path


def commit_all(repo: Path, message: str = "init") -> None:
    git("add", "-A", cwd=repo)
    git("commit", "-m", message, cwd=repo)


def clone_with_origin(tmp_path: Path, branch: str = "feat/test") -> Path:
    """Клон с remote origin: base-коммит на main, локальная ветка branch."""
    seed = init_repo(tmp_path / "seed")
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "base")
    git("clone", "--bare", str(seed), str(tmp_path / "origin.git"), cwd=tmp_path)
    clone = tmp_path / "clone"
    git("clone", str(tmp_path / "origin.git"), str(clone), cwd=tmp_path)
    git("switch", "-c", branch, cwd=clone)
    return clone


def run_script(name: str, *args: str, cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPTS / name), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=base_env(**env),
    )
