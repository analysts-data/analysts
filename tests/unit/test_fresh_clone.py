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
        # до make run порт свободен (BUSY=1 — там уже чужой сервер)
        "  */api/health)\n"
        f'    if [ "${{BUSY:-0}}" != "1" ] && ! grep -q "^make run" {DIR_LOG}; then exit 7; fi\n'
        "    echo '{\"ok\": true}' ;;\n"
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
    page = "curl -sf http://127.0.0.1:8000/"
    health = f"{page}api/health"
    assert logged == [health, "uv sync", "make check", "make run PORT=8000", health, page]
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
    assert "make run PORT=8000" in calls(bin_dir)  # сервер успели запустить


def test_busy_port_fails_before_starting_the_server(tmp_path: Path) -> None:
    """На 10:00 сервер команды уже на 8000: health чужого сервера не выдаётся за клон."""
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = run_clone(bin_dir, tmp_path, seed_repo(tmp_path), BUSY="1")

    assert result.returncode != 0
    assert "порт 8000 занят" in result.stderr
    assert not any(line.startswith("make run") for line in calls(bin_dir))


def test_port_variable_moves_the_clone_server(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = run_clone(bin_dir, tmp_path, seed_repo(tmp_path), PORT="18123")

    assert result.returncode == 0, result.stdout + result.stderr
    logged = calls(bin_dir)
    assert "make run PORT=18123" in logged
    assert all("18123" in line for line in logged if line.startswith("curl"))


def test_make_run_takes_the_port_variable() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")

    assert "PORT ?= 8000" in makefile
    assert "--port $(PORT)" in makefile
