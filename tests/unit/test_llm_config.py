"""Режим оценки из интерфейса: проверка, применение, сохранение поверх .env; ключи наружу не уходят."""

import pytest
from pydantic import SecretStr

from cqa.adapters.store import Store, connect
from cqa.services.errors import Conflict, Invalid
from cqa.services.llm_config import configure, effective, view
from cqa.settings import Settings

BODY = {
    "llm_base_url": "https://api.example.test/v1",
    "llm_model": "m1",
    "llm_profile": "plain",
    "llm_api_key": "sk-new",
    "data_where": "external",
    "anonymize": True,
    "verifier": None,
    "jev_api_key": "",
    "allow_real_data": False,
}


@pytest.fixture
def store() -> Store:
    return Store(connect(":memory:"))


def _live() -> Settings:
    return Settings(
        _env_file=None, llm_mode="live", llm_base_url="https://kz.test/v1", llm_api_key=SecretStr("sk-env")
    )


def test_configure_applies_and_saves_the_new_mode(store: Store) -> None:
    applied: list[Settings] = []
    result = configure(store, _live(), BODY, applied.append)
    assert applied == [result]
    assert (result.llm_base_url, result.llm_model, result.data_where) == (
        "https://api.example.test/v1",
        "m1",
        "external",
    )
    assert result.llm_api_key is not None and result.llm_api_key.get_secret_value() == "sk-new"
    again = effective(_live(), store.overrides())
    assert again.llm_api_key is not None and again.llm_api_key.get_secret_value() == "sk-new"
    assert again.llm_model == "m1"


def test_empty_key_keeps_the_saved_one(store: Store) -> None:
    configure(store, _live(), BODY, lambda s: None)
    result = configure(
        store, effective(_live(), store.overrides()), {**BODY, "llm_api_key": ""}, lambda s: None
    )
    assert result.llm_api_key is not None and result.llm_api_key.get_secret_value() == "sk-new"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"llm_base_url": "ftp://x"}, "http"),
        ({"llm_profile": "nope"}, "профиль"),
        ({"verifier": "jev"}, "CQA_JEV_API_KEY"),
    ],
)
def test_bad_mode_is_invalid_and_nothing_is_saved(store: Store, change: dict, message: str) -> None:
    applied: list[Settings] = []
    with pytest.raises(Invalid, match=message):
        configure(store, _live(), {**BODY, **change}, applied.append)
    assert (applied, store.overrides()) == ([], {})


def test_live_mode_without_any_key_is_invalid(store: Store) -> None:
    settings = Settings(_env_file=None, llm_mode="live")
    with pytest.raises(Invalid, match="CQA_LLM_API_KEY"):
        configure(store, settings, {**BODY, "llm_api_key": ""}, lambda s: None)


def test_conflict_while_applying_saves_nothing(store: Store) -> None:
    def busy(_: Settings) -> None:
        raise Conflict("Запуск 1 ещё идёт")

    with pytest.raises(Conflict):
        configure(store, _live(), BODY, busy)
    assert store.overrides() == {}


def test_view_shows_the_mode_but_never_the_keys() -> None:
    shown = view(effective(_live(), {"jev_api_key": "jev-secret", "verifier": "jev"}))
    assert shown["has_llm_key"] is True and shown["has_jev_key"] is True
    assert shown["verifier"] == "jev" and "plain" in shown["profiles"]
    assert "sk-env" not in repr(shown) and "jev-secret" not in repr(shown)
