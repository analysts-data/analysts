"""scripts/secret_scan.sh: сигнатуры секретов в отслеживаемых файлах."""

from __future__ import annotations

from pathlib import Path

import pytest
from gitrepo import commit_all, init_repo, run_script

# Сигнатуры собираются из частей, чтобы сам тест не содержал их дословно.
SIG = "si" + "g="
APIKEY = "api" + "key_"
SK = "s" + "k-" + "0123456789abcdef"
GHO = "gh" + "o_"
PP = "powerplatform" + ".com"
DYNDL = "dynamics" + ".com/api/filedownload"


def make_repo_with(tmp_path: Path, filename: str, content: str) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / filename).write_text(content, encoding="utf-8")
    commit_all(repo, "init")
    return repo


def test_clean_repo_passes(tmp_path: Path) -> None:
    repo = make_repo_with(tmp_path, "notes.md", "обычный текст без секретов")

    result = run_script("secret_scan.sh", cwd=repo)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("secret", [SIG, APIKEY, SK, GHO, PP, DYNDL])
def test_planted_secret_is_reported(tmp_path: Path, secret: str) -> None:
    repo = make_repo_with(tmp_path, "leaked.txt", f"токен {secret} в тексте")

    result = run_script("secret_scan.sh", cwd=repo)

    assert result.returncode != 0
    assert "leaked.txt" in result.stdout + result.stderr


def test_env_example_is_skipped(tmp_path: Path) -> None:
    repo = make_repo_with(tmp_path, ".env.example", f"CQA_ORG_TOKEN={SIG}example\n")

    result = run_script("secret_scan.sh", cwd=repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_untracked_file_is_ignored(tmp_path: Path) -> None:
    repo = make_repo_with(tmp_path, "notes.md", "чистый файл")
    (repo / "local_draft.txt").write_text(f"черновик {SIG} куда-то", encoding="utf-8")

    result = run_script("secret_scan.sh", cwd=repo)

    assert result.returncode == 0, result.stdout + result.stderr
