"""Белый список записей ответов моделей (eval-and-delivery 5.2): лишний файл — ошибка."""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
CASSETTES = Path(__file__).resolve().parents[1] / "cassettes"


def test_every_cassette_is_replayed() -> None:
    if os.environ.get("CQA_CASSETTE_AUDIT") != "1":
        pytest.skip("белый список собирает полный прогон cassette и e2e: make e2e")
    used = set(Path(os.environ["CQA_CASSETTE_LOG"]).read_text(encoding="utf-8").split())
    files = {f"{p.parent.name}/{p.name}" for p in CASSETTES.glob("*/*.json")}  # llm/ и jev/
    unused = sorted(files - used)
    assert not unused, f"{len(unused)} записей не нужны ни одному тесту cassette или e2e: {unused[:5]}"
