"""Витрина для показа (`make showcase`): 40 синтетических диалогов оцениваются по записанным ответам.

Тест держит записи `tests/cassettes/llm/` для витрины в белом списке (`make e2e`), а
`CQA_LLM_MODE=record` этим же тестом их пишет.
"""

import json
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.settings import Settings

pytestmark = pytest.mark.cassette

SHOWCASE = Path(__file__).resolve().parents[1] / "fixtures" / "showcase_set.json"
RECORDS = json.loads(SHOWCASE.read_text(encoding="utf-8"))["data"]["records"]


def test_showcase_set_spreads_over_operators_languages_channels_and_days() -> None:
    assert len(RECORDS) == 40
    assert set(Counter(r["operator"] for r in RECORDS).values()) == {8}
    assert Counter(r["language"] for r in RECORDS) == {"RU": 24, "KZ": 8, "EN": 8}
    assert Counter(r["channel"] for r in RECORDS) == {"agent chat": 32, "voice call": 8}
    assert len({r["started_at"][:10] for r in RECORDS}) == 5
    assert not any(r["audio_url"] for r in RECORDS)


def test_every_showcase_dialog_is_evaluated_on_every_criterion(tmp_path: Path) -> None:
    settings = Settings(db_path=str(tmp_path / "showcase.db"))  # CQA_LLM_MODE: replay, record — запись
    if settings.llm_mode == "replay":  # 400 вызовов: окно CQA_LLM_RPM держало бы тест минуты, сети нет
        settings = settings.model_copy(update={"llm_rpm": 0})
    with TestClient(create_app(settings)) as api:
        json_body = {"Content-Type": "application/json"}
        added = api.post("/api/datasets/upload", content=SHOWCASE.read_bytes(), headers=json_body)
        assert added.json() == {"added": 40, "skipped": 0}
        run_id = api.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"]
        while (run := api.get(f"/api/runs/{run_id}").json())["status"] == "running":
            time.sleep(0.2)
        assert run["errors"] == []
        state = api.get("/api/state").json()
    cids = [c["id"] for c in state["checklist"]["criteria"]]
    missing = {d["id"]: [c for c in cids if c not in d["res"]] for d in state["dialogs"]}
    assert len(missing) == 40
    assert not {k: v for k, v in missing.items() if v}
