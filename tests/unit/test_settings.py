from pathlib import Path

import pytest

from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[2]

# table "Settings" in design/ports.md
DEFAULTS = {
    "llm_mode": "replay",
    "llm_base_url": None,
    "llm_api_key": None,
    "llm_model": "qwen3-6",
    "llm_profile": "plain",
    "llm_reasoning": "on",
    "llm_max_parallel": 4,
    "llm_rpm": 120,
    "llm_timeout_s": 180.0,
    "llm_price_in": 0.0,
    "llm_price_out": 0.0,
    "llm_provider": "env",
    "providers": {},
    "openrouter_api_key": None,
    "verifier": None,
    "evaluator": "llm",
    "routing": None,
    "jev_api_key": None,
    "anonymize": True,
    "data_where": "kz",
    "allow_real_data": False,
    "org_api_url": None,
    "raw_dir": Path("data/raw"),
    "audio_shift_s": 0.25,
    "audio_shift_paused_s": 4.5,
    "db_path": "data/cqa.db",
    "eval_dataset": Path("data/dev.json"),
    "holdout_dir": None,
    "telemetry": "on",
    "telemetry_retention_days": 30,
    "eval_reports_dir": Path("eval/reports"),
    "results_dir": Path("results"),
    "access_token": None,
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DEFAULTS:
        monkeypatch.delenv(f"CQA_{name.upper()}", raising=False)


def test_defaults_are_scenario_4_without_keys_or_org_url() -> None:
    assert Settings(_env_file=None).model_dump() == DEFAULTS


def test_empty_verifier_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_VERIFIER", "")
    monkeypatch.setenv("CQA_LLM_MAX_PARALLEL", "2")
    settings = Settings(_env_file=None)
    assert settings.verifier is None
    assert settings.llm_max_parallel == 2


def test_env_example_lists_every_field_without_values() -> None:
    lines = [ln for ln in (ROOT / ".env.example").read_text().splitlines() if ln and not ln.startswith("#")]
    assert {ln.split("=", 1)[0] for ln in lines} == {f"CQA_{name.upper()}" for name in Settings.model_fields}
    assert all(ln.endswith("=") for ln in lines)


def test_env_example_copied_as_env_gives_defaults() -> None:
    assert Settings(_env_file=ROOT / ".env.example").model_dump() == DEFAULTS
