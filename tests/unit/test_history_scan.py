"""scripts/secret_scan.sh --history: секреты и запрещённые пути во всей истории.

Сценарии из spec release-and-runbook: ключ удалён, но остался в истории;
данные (data/dev.json) были закоммичены и удалены.
"""

from __future__ import annotations

from pathlib import Path

from gitrepo import commit_all, git, init_repo, run_script

# Сигнатуры собираются из частей, чтобы сам тест не содержал их дословно.
APIKEY = "api" + "key_"
HEX = "0123456789abcdef"
SIG = "si" + "g="


def leak_commit(repo: Path) -> str:
    """sha коммита, добавившего утечку (HEAD после первого коммита)."""
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def test_clean_history_passes(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "notes.md").write_text("обычный текст без секретов", encoding="utf-8")
    commit_all(repo, "init")

    result = run_script("secret_scan.sh", "--history", cwd=repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_removed_secret_stays_in_history(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "leaked.txt").write_text(f"токен {APIKEY}{HEX} в тексте", encoding="utf-8")
    commit_all(repo, "leak")
    bad = leak_commit(repo)
    (repo / "leaked.txt").unlink()
    commit_all(repo, "remove")

    plain = run_script("secret_scan.sh", cwd=repo)
    history = run_script("secret_scan.sh", "--history", cwd=repo)

    assert plain.returncode == 0, plain.stdout + plain.stderr
    assert history.returncode != 0
    out = history.stdout + history.stderr
    assert bad in out
    assert "leaked.txt" in out


def test_secret_signature_in_history_is_reported(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "token.txt").write_text(f"ссылка {SIG}abc и всё", encoding="utf-8")
    commit_all(repo, "leak")
    bad = leak_commit(repo)
    (repo / "token.txt").unlink()
    commit_all(repo, "remove")

    result = run_script("secret_scan.sh", "--history", cwd=repo)

    assert result.returncode != 0
    assert bad in result.stdout + result.stderr


def test_data_file_in_history_is_reported(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    data = repo / "data"
    data.mkdir()
    (data / "dev.json").write_text("{}", encoding="utf-8")
    commit_all(repo, "data")
    (data / "dev.json").unlink()
    commit_all(repo, "remove data")

    result = run_script("secret_scan.sh", "--history", cwd=repo)

    assert result.returncode != 0
    assert "data/dev.json" in result.stdout + result.stderr


def test_env_in_history_is_reported(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".env").write_text("CQA_LLM_API_KEY=x\n", encoding="utf-8")
    (repo / ".env.example").write_text("CQA_LLM_API_KEY=\n", encoding="utf-8")
    commit_all(repo, "env")
    (repo / ".env").unlink()
    commit_all(repo, "remove env")

    result = run_script("secret_scan.sh", "--history", cwd=repo)

    assert result.returncode != 0
    out = result.stdout + result.stderr
    assert ".env" in out
    assert ".env.example" not in out


def test_audio_and_db_in_history_are_reported(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "call.mp3").write_bytes(b"id3")
    (repo / "note.wav").write_bytes(b"riff")
    (repo / "cqa.db").write_bytes(b"sqlite")
    (repo / "cqa.sqlite").write_bytes(b"sqlite")
    commit_all(repo, "media")
    for name in ("call.mp3", "note.wav", "cqa.db", "cqa.sqlite"):
        (repo / name).unlink()
    commit_all(repo, "remove media")

    result = run_script("secret_scan.sh", "--history", cwd=repo)

    assert result.returncode != 0
    out = result.stdout + result.stderr
    for name in ("call.mp3", "note.wav", "cqa.db", "cqa.sqlite"):
        assert name in out
