"""scripts/publish.sh: публикация после проверок и подтверждения капитана.

Заглушки gh, git, secret_scan.sh и fresh_clone.sh в PATH пишут вызовы в логи;
без совпадения имени и при провале проверки gh не вызывается.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from gitrepo import run_script

REPO = "analysts-data/analysts"
URL = "https://github.com/analysts-data/analysts.git"
DIR_LOG = '$(dirname "$0")'


def stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    def stub(name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(stat.S_IRWXU)

    stub("gh", f'#!/bin/sh\necho "gh $*" >> {DIR_LOG}/gh.log\n')
    stub(
        "git",
        f'#!/bin/sh\necho "git GIT_TERMINAL_PROMPT=$GIT_TERMINAL_PROMPT $*" >> {DIR_LOG}/git.log\n',
    )
    stub(
        "secret_scan.sh",
        f'#!/bin/sh\necho "secret_scan $*" >> {DIR_LOG}/secret_scan.log\n'
        'if [ "${SCAN_FAIL:-0}" = "1" ]; then exit 1; fi\n',
    )
    stub(
        "fresh_clone.sh",
        f'#!/bin/sh\necho "fresh_clone $*" >> {DIR_LOG}/fresh_clone.log\n'
        'if [ "${CLONE_FAIL:-0}" = "1" ]; then exit 1; fi\n',
    )
    return bin_dir


def publish(
    bin_dir: Path, tmp_path: Path, *args: str, stdin: str = "", **env: str
) -> subprocess.CompletedProcess[str]:
    return run_script(
        "publish.sh",
        *args,
        cwd=tmp_path,
        input=stdin,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        TMPDIR=str(tmp_path / "tmp"),
        **env,
    )


def log(bin_dir: Path, name: str) -> str:
    path = bin_dir / f"{name}.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_publish_after_confirmation(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = publish(bin_dir, tmp_path, REPO, stdin=f"{REPO}\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "https://github.com/analysts-data/analysts" in result.stdout
    assert "--history" in log(bin_dir, "secret_scan")
    assert URL in log(bin_dir, "fresh_clone")
    assert (
        log(bin_dir, "gh").strip()
        == f"gh repo edit {REPO} --visibility public --accept-visibility-change-consequences"
    )
    git_log = log(bin_dir, "git")
    assert "GIT_TERMINAL_PROMPT=0" in git_log
    assert f"clone {URL}" in git_log


def test_wrong_confirmation_name_cancels(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = publish(bin_dir, tmp_path, REPO, stdin="other/repo\n")

    assert result.returncode != 0
    assert "отменена" in result.stdout + result.stderr
    assert log(bin_dir, "gh") == ""
    assert "--history" in log(bin_dir, "secret_scan")  # проверки были до подтверждения


def test_failed_history_scan_stops_before_confirmation(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = publish(bin_dir, tmp_path, REPO, SCAN_FAIL="1")

    assert result.returncode != 0
    assert log(bin_dir, "fresh_clone") == ""
    assert log(bin_dir, "gh") == ""


def test_failed_fresh_clone_never_calls_gh(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = publish(bin_dir, tmp_path, REPO, CLONE_FAIL="1", stdin=f"{REPO}\n")

    assert result.returncode != 0
    assert log(bin_dir, "gh") == ""


def test_repo_name_without_owner_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    bin_dir = stubs(tmp_path)

    result = publish(bin_dir, tmp_path, "analysts")

    assert result.returncode == 2
    assert log(bin_dir, "gh") == ""
    assert log(bin_dir, "secret_scan") == ""
