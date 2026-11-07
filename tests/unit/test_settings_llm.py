"""Поля Settings трека llm-evaluation и блоки сценариев в .env.example."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[2]

LLM_VARS = (
    "CQA_LLM_MODE",
    "CQA_LLM_BASE_URL",
    "CQA_LLM_API_KEY",
    "CQA_LLM_MODEL",
    "CQA_LLM_PROFILE",
    "CQA_LLM_REASONING",
    "CQA_LLM_MAX_PARALLEL",
    "CQA_LLM_RPM",
    "CQA_LLM_TIMEOUT_S",
    "CQA_LLM_PRICE_IN",
    "CQA_LLM_PRICE_OUT",
    "CQA_VERIFIER",
    "CQA_JEV_API_KEY",
    "CQA_ANONYMIZE",
    "CQA_ALLOW_REAL_DATA",
    "CQA_DATA_WHERE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in LLM_VARS:
        monkeypatch.delenv(var, raising=False)


def test_scenario_5_environment_switches_provider_and_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var, value in {
        "CQA_LLM_MODE": "live",
        "CQA_LLM_BASE_URL": "https://api.deepseek.com",
        "CQA_LLM_API_KEY": "sk-deepseek",
        "CQA_LLM_PROFILE": "deepseek",
        "CQA_LLM_MAX_PARALLEL": "64",
        "CQA_LLM_RPM": "0",
        "CQA_LLM_PRICE_IN": "0.435",
        "CQA_LLM_PRICE_OUT": "0.87",
        "CQA_VERIFIER": "jev",
        "CQA_JEV_API_KEY": "sk-jev",
        "CQA_ANONYMIZE": "1",
        "CQA_DATA_WHERE": "external",
    }.items():
        monkeypatch.setenv(var, value)
    settings = Settings(_env_file=None)
    assert settings.llm_mode == "live"
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_api_key == SecretStr("sk-deepseek")
    assert settings.llm_profile == "deepseek"
    assert settings.llm_max_parallel == 64
    assert settings.llm_rpm == 0
    assert settings.llm_price_in == 0.435
    assert settings.llm_price_out == 0.87
    assert settings.verifier == "jev"
    assert settings.jev_api_key == SecretStr("sk-jev")
    assert settings.anonymize is True
    assert settings.data_where == "external"


def test_allow_real_data_is_set_by_human_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_ALLOW_REAL_DATA", "1")
    settings = Settings(_env_file=None)
    assert settings.allow_real_data is True


def test_env_example_documents_scenarios_4_and_5() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    # сценарий 4 (по умолчанию): провайдер в РК, plain, без второго мнения
    assert "# CQA_LLM_BASE_URL=https://llm.alem.ai/v1" in text
    assert "# CQA_LLM_PROFILE=plain" in text
    assert "# CQA_LLM_MAX_PARALLEL=4" in text
    assert "# CQA_LLM_RPM=120" in text
    # сценарий 5 (запасной): DeepSeek V4 Pro + Jev, без лимита в минуту
    assert "# CQA_LLM_BASE_URL=https://api.deepseek.com" in text
    assert "# CQA_LLM_PROFILE=deepseek" in text
    assert "# CQA_LLM_MAX_PARALLEL=64" in text
    assert "# CQA_LLM_RPM=0" in text
    assert "# CQA_LLM_PRICE_IN=0.435" in text
    assert "# CQA_LLM_PRICE_OUT=0.87" in text
    assert "# CQA_VERIFIER=jev" in text
    assert "# CQA_DATA_WHERE=external" in text
