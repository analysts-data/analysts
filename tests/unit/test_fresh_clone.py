"""scripts/fresh_clone.sh: свежий клон проходит шаги README без правок.

Заглушки uv, make, curl и sleep в PATH записывают вызовы; git настоящий —
репозиторий временный. Каталог клона скрипт не удаляет (rm -rf запрещён).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from gitrepo import commit_all, init_repo, run_script

DIR_LOG = '$(dirname "$0")/calls.log'


def stubs(tmp_path: Path) -> Path:
    """bin/ с заглушками: uv, make (MAKE_FAIL=1 — падает), curl, sleep."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    def stub(name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(stat.S_IRWXU)

    stub("uv", f'#!/bin/sh\necho "uv $*" >> {DIR_LOG}\n')
    stub(
        "make",
        f'#!/bin/sh\necho "make $*" >> {DIR_LOG}\nif [ "${{MAKE_FAIL:-0}}" = "1" ]; then exit 1; fi\n',
    )
    stub(
        "curl",
        f'#!/bin/sh\necho "curl $*" >> {DIR_LOG}\n'
        'if [ "${CURL_FAIL:-0}" = "1" ]; then exit 1; fi\n'
        'case "$*" in\n'
        "  */api/health) echo '{\"ok\": true}' ;;\n"
        "  *) echo '<cqa-app></cqa-app>' ;;\n"
        "esac\n",
    )
    stub("sleep", "#!/bin/sh\nexit 0\n")
    return bin_dir


def seed_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "seed")
    (repo / "README.md").write_text("# CQA\n", encoding="utf-8")
    (repo / ".env.example").write_text("CQA_LLM_MODE=\n", encoding="utf-8")
    commit_all(repo, "base")
    return repo


def run_clone(bin_dir: Path, tmp_path: Path, repo: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return run_script(
        "fresh_clone.sh",
        str(repo),
        cwd=tmp_path,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        TMPDIR=str(tmp_path / "tmp"),
        **env,
    )


def calls(bin_dir: Path) -> list[str]:
    log = bin_dir / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def clone_dir(result: subprocess.CompletedProcess[str]) -> Path:
    line = next(line for line in result.stdout.splitlines() if line.startswith("каталог клона: "))
    return Path(line.removeprefix("каталог клона: ").strip())


def test_fresh_clone_runs_readme_steps_and_keeps_dir(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)
    repo = seed_repo(tmp_path)

    result = run_clone(bin_dir, tmp_path, repo)

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(bin_dir)
    order = [
        logged.index(line)
        for line in (
            "uv sync",
            "make check",
            "make run",
            next(line for line in logged if line.endswith("/api/health")),
            next(line for line in logged if line.startswith("curl") and line.endswith("8000/")),
        )
    ]
    assert order == sorted(order), logged
    kept = clone_dir(result)
    assert (kept / "repo").is_dir()  # каталог не удалён
    assert (kept / "repo" / ".env").is_file()  # шаг cp .env.example .env


def test_failing_make_check_names_the_step(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)
    repo = seed_repo(tmp_path)

    result = run_clone(bin_dir, tmp_path, repo, MAKE_FAIL="1")

    assert result.returncode != 0
    out = result.stdout + result.stderr
    assert "make check" in out
    assert "не пройден" in out
    assert "каталог клона:" not in result.stdout


def test_unreachable_health_names_the_step(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)
    repo = seed_repo(tmp_path)

    result = run_clone(bin_dir, tmp_path, repo, CURL_FAIL="1")

    assert result.returncode != 0
    out = result.stdout + result.stderr
    assert "curl /api/health" in out
    assert "make run" in calls(bin_dir)  # сервер успели запустить
