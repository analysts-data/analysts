"""Режим оценки из интерфейса: провайдеры моделей, выбор основной модели и второго мнения поверх .env."""

from typing import Any

import pytest
from pydantic import SecretStr

from cqa.adapters.store import Store, connect
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.llm_config import (
    OPENROUTER,
    configure,
    delete_provider,
    effective,
    put_provider,
    run_settings,
    view,
)
from cqa.settings import Settings

BODY: dict[str, Any] = {
    "llm_provider": "env",
    "anonymize": True,
    "verifier": None,
    "jev_api_key": "",
    "allow_real_data": False,
}
DS: dict[str, Any] = {
    "label": "DeepSeek",
    "base_url": "https://api.deepseek.test",
    "model": "ds-pro",
    "profile": "deepseek",
    "where": "external",
    "key": "sk-ds",
}


@pytest.fixture
def store() -> Store:
    return Store(connect(":memory:"))


def _live(**kw: Any) -> Settings:
    base = effective(
        Settings(
            _env_file=None,
            llm_mode="live",
            llm_base_url="https://kz.test/v1",
            llm_api_key=SecretStr("sk-env"),
            **kw,
        ),
        {},
    )
    return base


def _with_ds(store: Store) -> Settings:
    return put_provider(store, _live(), "ds", DS, lambda s: None)


def test_env_provider_is_seeded_from_settings_and_is_the_main_model() -> None:
    settings = _live()
    shown = view(settings)
    assert shown["llm_provider"] == "env"
    assert shown["providers"][0] == (
        {
            "id": "env",
            "label": "Из .env",
            "base_url": "https://kz.test/v1",
            "model": "qwen3-6",
            "profile": "plain",
            "where": "kz",
            "has_key": True,
        }
    )
    assert (settings.llm_base_url, settings.data_where) == ("https://kz.test/v1", "kz")


def test_new_provider_is_saved_and_survives_a_restart(store: Store) -> None:
    applied: list[Settings] = []
    result = put_provider(store, _live(), "ds", DS, applied.append)
    assert applied == [result]
    assert result.llm_provider == "env" and result.llm_base_url == "https://kz.test/v1"
    again = effective(Settings(_env_file=None, llm_base_url="https://kz.test/v1"), store.overrides())
    assert [p["id"] for p in view(again)["providers"]] == ["env", OPENROUTER, "ds"]
    key = again.providers["ds"].key
    assert key is not None and key.get_secret_value() == "sk-ds"


def test_empty_key_keeps_the_saved_one(store: Store) -> None:
    result = put_provider(store, _with_ds(store), "ds", {**DS, "key": "", "model": "ds-v5"}, lambda s: None)
    provider = result.providers["ds"]
    assert provider.model == "ds-v5"
    assert provider.key is not None and provider.key.get_secret_value() == "sk-ds"


def test_configure_switches_the_main_model_to_a_provider(store: Store) -> None:
    result = configure(store, _with_ds(store), {**BODY, "llm_provider": "ds"}, lambda s: None)
    assert (result.llm_base_url, result.llm_model, result.llm_profile, result.data_where) == (
        "https://api.deepseek.test",
        "ds-pro",
        "deepseek",
        "external",
    )
    assert result.llm_api_key is not None and result.llm_api_key.get_secret_value() == "sk-ds"
    again = effective(_live(), store.overrides())
    assert (again.llm_provider, again.llm_model) == ("ds", "ds-pro")


def test_editing_the_main_provider_changes_the_main_model(store: Store) -> None:
    settings = configure(store, _with_ds(store), {**BODY, "llm_provider": "ds"}, lambda s: None)
    result = put_provider(store, settings, "ds", {**DS, "model": "ds-v5", "key": ""}, lambda s: None)
    assert result.llm_model == "ds-v5"


def test_verifier_can_be_a_provider(store: Store) -> None:
    result = configure(store, _with_ds(store), {**BODY, "verifier": "ds"}, lambda s: None)
    assert (result.verifier, result.llm_provider) == ("ds", "env")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"llm_provider": "nope"}, "nope"),
        ({"verifier": "nope"}, "nope"),
        ({"verifier": "jev"}, "CQA_JEV_API_KEY"),
        ({"evaluator": "jev"}, "CQA_JEV_API_KEY"),
    ],
)
def test_bad_choice_is_invalid_and_nothing_is_saved(store: Store, change: dict, message: str) -> None:
    applied: list[Settings] = []
    with pytest.raises(Invalid, match=message):
        configure(store, _live(), {**BODY, **change}, applied.append)
    assert (applied, store.overrides()) == ([], {})


@pytest.mark.parametrize(
    ("pid", "change", "message"),
    [
        ("ds", {"base_url": "ftp://x"}, "http"),
        ("ds", {"profile": "nope"}, "профиль"),
        ("Bad id", {}, "латиница"),
    ],
)
def test_bad_provider_is_invalid_and_nothing_is_saved(
    store: Store, pid: str, change: dict, message: str
) -> None:
    with pytest.raises(Invalid, match=message):
        put_provider(store, _live(), pid, {**DS, **change}, lambda s: None)
    assert store.overrides() == {}


def test_main_model_without_any_key_is_invalid(store: Store) -> None:
    settings = effective(Settings(_env_file=None, llm_mode="live", llm_base_url="https://kz.test/v1"), {})
    with pytest.raises(Invalid, match="CQA_LLM_API_KEY"):
        configure(store, settings, BODY, lambda s: None)


def test_conflict_while_applying_saves_nothing(store: Store) -> None:
    def busy(_: Settings) -> None:
        raise Conflict("Запуск 1 ещё идёт")

    with pytest.raises(Conflict):
        configure(store, _live(), BODY, busy)
    with pytest.raises(Conflict):
        put_provider(store, _live(), "ds", DS, busy)
    assert store.overrides() == {}


def test_unused_provider_is_deleted(store: Store) -> None:
    result = delete_provider(store, _with_ds(store), "ds", lambda s: None)
    assert list(result.providers) == ["env", OPENROUTER]
    assert list(effective(_live(), store.overrides()).providers) == ["env", OPENROUTER]


def test_provider_in_use_or_from_env_is_not_deleted(store: Store) -> None:
    settings = configure(store, _with_ds(store), {**BODY, "verifier": "ds"}, lambda s: None)
    with pytest.raises(Conflict, match="второе мнение"):
        delete_provider(store, settings, "ds", lambda s: None)
    with pytest.raises(Conflict, match="основная"):
        delete_provider(store, settings, "env", lambda s: None)
    with pytest.raises(NotFound):
        delete_provider(store, settings, "nope", lambda s: None)


def test_view_shows_the_mode_but_never_the_keys(store: Store) -> None:
    shown = view(effective(_with_ds(store), {"jev_api_key": "jev-secret", "verifier": "jev"}))
    assert shown["has_llm_key"] is True and shown["has_jev_key"] is True
    assert shown["verifier"] == "jev" and "plain" in shown["profiles"]
    assert all("key" not in p for p in shown["providers"])
    assert not {"sk-env", "sk-ds", "jev-secret"} & set(repr(shown).split("'"))


def test_env_provider_is_read_only(store: Store) -> None:
    with pytest.raises(Invalid, match=".env"):
        put_provider(store, _live(), "env", DS, lambda s: None)


def test_providers_from_env_file_are_listed_and_the_saved_list_replaces_them(store: Store) -> None:
    raw = {"ds": {**DS, "key": "sk-ds"}}
    settings = effective(Settings(_env_file=None, providers=raw), {})
    assert list(settings.providers) == ["env", OPENROUTER, "ds"]
    result = put_provider(store, settings, "local", {**DS, "where": "local"}, lambda s: None)
    assert list(effective(Settings(_env_file=None, providers=raw), store.overrides()).providers) == [
        "env",
        OPENROUTER,
        "ds",
        "local",
    ]
    assert list(delete_provider(store, result, "ds", lambda s: None).providers) == [
        "env",
        OPENROUTER,
        "local",
    ]


def test_jev_only_mode_needs_the_jev_key_but_not_the_llm_key(store: Store) -> None:
    settings = effective(Settings(_env_file=None, llm_mode="live"), {})
    result = configure(store, settings, {**BODY, "evaluator": "jev", "jev_api_key": "j"}, lambda s: None)
    assert result.evaluator == "jev"
    assert view(result)["evaluator"] == "jev"


def test_mode_names_jev_as_the_model_and_no_second_opinion_in_jev_only_mode() -> None:
    from cqa.services.state import mode_from_settings

    mode = mode_from_settings(effective(_live(), {"evaluator": "jev", "verifier": "jev"}))
    assert (mode.model, mode.verifier) == ("jev-latest", None)
    assert view(_live())["evaluator"] == "llm"


JEV_ROUTER = {
    "id": OPENROUTER,
    "label": "OpenRouter — Jev Router",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "typesafe/jev-router",
    "profile": "plain",
    "where": "external",
}


def test_openrouter_jev_is_always_listed_as_an_external_provider_without_a_key() -> None:
    assert view(_live())["providers"][1] == {**JEV_ROUTER, "has_key": False}


def test_openrouter_key_from_env_seeds_the_preset_and_stays_out_of_the_db(store: Store) -> None:
    settings = _live(openrouter_api_key=SecretStr("sk-or-env"))
    assert view(settings)["providers"][1]["has_key"] is True
    put_provider(store, settings, "ds", DS, lambda s: None)
    assert OPENROUTER not in store.overrides()["providers"]


def test_openrouter_jev_takes_only_model_and_key_and_delete_resets_it(store: Store) -> None:
    body = {
        **DS,
        "label": "x",
        "base_url": "https://evil.test",
        "where": "kz",
        "model": "typesafe/next",
        "key": "sk-or",
    }
    put_provider(store, _live(), OPENROUTER, body, lambda s: None)
    edited = effective(_live(), store.overrides())
    shown = view(edited)["providers"][1]
    assert shown == {**JEV_ROUTER, "model": "typesafe/next", "has_key": True}
    reset = delete_provider(store, edited, OPENROUTER, lambda s: None)
    assert view(reset)["providers"][1] == {**JEV_ROUTER, "has_key": False}
    assert view(effective(_live(), store.overrides()))["providers"][1] == {**JEV_ROUTER, "has_key": False}


def test_openrouter_jev_as_main_model_shows_external_data_in_the_mode(store: Store) -> None:
    from cqa.services.state import mode_from_settings

    settings = put_provider(store, _live(), OPENROUTER, {**JEV_ROUTER, "key": "sk-or"}, lambda s: None)
    result = configure(store, settings, {**BODY, "llm_provider": OPENROUTER}, lambda s: None)
    mode = mode_from_settings(result)
    assert (mode.where, mode.model, result.llm_profile) == ("external", "typesafe/jev-router", "plain")


# --- настройки одного запуска (перепроверка другой моделью) ---


def test_run_override_swaps_the_main_model_and_verifier_for_one_run(store: Store) -> None:
    settings = _with_ds(store)
    got = run_settings(settings, {"llm_provider": "ds", "verifier": None})
    assert (got.llm_provider, got.llm_model, got.verifier) == ("ds", "ds-pro", None)
    assert settings.llm_provider == "env"  # saved mode stays as it was
    assert run_settings(settings, {}) == settings


def test_run_override_with_jev_only_needs_a_jev_key_outside_replay() -> None:
    with pytest.raises(Invalid, match="^Перепроверка: Нет ключа Jev"):
        run_settings(_live(), {"evaluator": "jev"})
    assert run_settings(_live(jev_api_key=SecretStr("jk")), {"evaluator": "jev"}).evaluator == "jev"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"llm_provider": "nope"}, "^override.llm_provider: нет провайдера nope$"),
        ({"verifier": "nope"}, "^override.verifier: нет провайдера nope$"),
    ],
)
def test_run_override_names_the_bad_field(override: dict[str, Any], message: str) -> None:
    with pytest.raises(Invalid, match=message):
        run_settings(_live(), override)
