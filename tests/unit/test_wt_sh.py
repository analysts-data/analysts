"""scripts/wt.sh: worktree на агента со ссылками на общие файлы."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from gitrepo import commit_all, git, init_repo, run_script

GITIGNORE = """\
.worktrees/
.venv/
.claude
.pi
AGENTS.md
AGENT.md
CLAUDE.md
openspec
"""

SHARED = ["openspec", "AGENTS.md", "CLAUDE.md", ".claude", ".pi"]


def main_copy(tmp_path: Path, shared: list[str] = SHARED) -> Path:
    """Основная копия: клон origin с .gitignore и незакоммиченными общими файлами."""
    seed = init_repo(tmp_path / "seed")
    (seed / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "base")
    git("clone", "--bare", str(seed), str(tmp_path / "origin.git"), cwd=tmp_path)
    main = tmp_path / "main"
    git("clone", str(tmp_path / "origin.git"), str(main), cwd=tmp_path)
    for name in shared:
        target = main / name
        if name in ("openspec", ".claude", ".pi"):
            target.mkdir()
            (target / "file.md").write_text("общий файл\n", encoding="utf-8")
        else:
            target.write_text("общий файл\n", encoding="utf-8")
    return main


def uv_stub(tmp_path: Path) -> tuple[str, Path]:
    """Поддельный uv в PATH: записывает каталог вызова и аргументы."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "uv"
    stub.write_text(
        '#!/bin/sh\nprintf \'%s %s\\n\' "$PWD" "$*" >> "$(dirname "$0")/uv.log"\n',
        encoding="utf-8",
    )
    stub.chmod(stat.S_IRWXU)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}", bin_dir / "uv.log"


def test_new_creates_worktree_with_shared_symlinks(tmp_path: Path) -> None:
    main = main_copy(tmp_path)
    origin_main = git("rev-parse", "origin/main", cwd=main).stdout.strip()

    result = run_script("wt.sh", "new", "llm-evaluation", "client", cwd=main, WT_SKIP_SYNC="1")

    assert result.returncode == 0, result.stderr
    wt = main / ".worktrees" / "llm-evaluation-client"
    assert wt.is_dir()
    assert git("rev-parse", "HEAD", cwd=wt).stdout.strip() == origin_main
    for name in SHARED:
        link = wt / name
        assert link.is_symlink(), name
        assert link.resolve() == (main / name).resolve()
    assert git("status", "--porcelain", cwd=wt).stdout == ""
    assert git("status", "--porcelain", cwd=main).stdout == ""


def test_new_links_only_existing_shared_files(tmp_path: Path) -> None:
    main = main_copy(tmp_path, shared=["openspec", "AGENTS.md"])

    result = run_script("wt.sh", "new", "review", "domain", cwd=main, WT_SKIP_SYNC="1")

    assert result.returncode == 0, result.stderr
    wt = main / ".worktrees" / "review-domain"
    assert (wt / "openspec").is_symlink()
    assert (wt / "AGENTS.md").is_symlink()
    assert not (wt / ".pi").exists()
    assert not (wt / "CLAUDE.md").exists()


def test_new_runs_uv_sync_inside_worktree(tmp_path: Path) -> None:
    main = main_copy(tmp_path)
    path, log = uv_stub(tmp_path)

    result = run_script("wt.sh", "new", "llm-evaluation", "client", cwd=main, PATH=path)

    assert result.returncode == 0, result.stderr
    wt = (main / ".worktrees" / "llm-evaluation-client").resolve()
    assert log.read_text(encoding="utf-8") == f"{wt} sync\n"


def test_new_twice_fails(tmp_path: Path) -> None:
    main = main_copy(tmp_path)
    first = run_script("wt.sh", "new", "x", "one", cwd=main, WT_SKIP_SYNC="1")
    assert first.returncode == 0, first.stderr

    second = run_script("wt.sh", "new", "x", "one", cwd=main, WT_SKIP_SYNC="1")

    assert second.returncode != 0


def test_rm_removes_worktree_and_branch(tmp_path: Path) -> None:
    main = main_copy(tmp_path)
    assert run_script("wt.sh", "new", "x", "one", cwd=main, WT_SKIP_SYNC="1").returncode == 0

    result = run_script("wt.sh", "rm", "x", "one", cwd=main)

    assert result.returncode == 0, result.stderr
    assert not (main / ".worktrees" / "x-one").exists()
    branches = git("branch", "--format=%(refname:short)", cwd=main).stdout.split()
    assert "feat/x-one" not in branches


def test_rm_missing_worktree_fails(tmp_path: Path) -> None:
    main = main_copy(tmp_path)

    result = run_script("wt.sh", "rm", "x", "one", cwd=main)

    assert result.returncode != 0
