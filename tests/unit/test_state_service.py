import pytest

from cqa.services.state import mode_from_settings
from cqa.settings import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CQA_DATA_WHERE", "CQA_ANONYMIZE", "CQA_LLM_MODEL", "CQA_VERIFIER"):
        monkeypatch.delenv(name, raising=False)


def test_mode_defaults_to_scenario_4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_VERIFIER", "")
    mode = mode_from_settings(Settings(_env_file=None))
    assert mode.model_dump(mode="json") == {
        "where": "kz",
        "anonymized": True,
        "model": "qwen3-6",
        "verifier": None,
    }


def test_mode_follows_fallback_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_DATA_WHERE", "external")
    monkeypatch.setenv("CQA_VERIFIER", "jev")
    mode = mode_from_settings(Settings(_env_file=None))
    assert (mode.where, mode.verifier) == ("external", "jev")
