"""Режим оценки из интерфейса: провайдеры моделей со своими ключами, основная модель, второе мнение,
место обработки, обезличивание, звонки.

Значения хранятся в базе поверх `.env` и применяются без перезапуска. Ключи в ответы не попадают.
"""

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from cqa.adapters.llm import PROFILES
from cqa.adapters.store import Store
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.settings import Provider, Settings

SECRETS = ("llm_api_key", "jev_api_key")
ENV = "env"  # провайдер из CQA_LLM_* (и полей llm_*, сохранённых до провайдеров): есть всегда, только чтение
OPENROUTER = "openrouter-jev"  # Jev Router через OpenRouter: есть всегда, меняются только модель и ключ
_ID = re.compile(r"[a-z0-9-]{1,32}")
Apply = Callable[[Settings], None]


def as_llm(provider: Provider) -> dict[str, Any]:
    """Поля основной модели в `Settings`: их читают ChatClient, `config_error` и плашка `mode`."""
    return {
        "llm_base_url": provider.base_url,
        "llm_model": provider.model,
        "llm_profile": provider.profile,
        "llm_api_key": provider.key,
        "data_where": provider.where,
    }


def openrouter(settings: Settings) -> Provider:
    """Встроенный провайдер по умолчанию; ключ — CQA_OPENROUTER_API_KEY. `DELETE` возвращает его к этому."""
    return Provider(
        label="OpenRouter — Jev Router",
        base_url="https://openrouter.ai/api/v1",
        model="typesafe/jev-router",
        profile="plain",  # только стандартные поля OpenAI
        where="external",
        key=settings.openrouter_api_key,
    )


def effective(settings: Settings, overrides: Mapping[str, Any]) -> Settings:
    """`settings` с сохранёнными из интерфейса значениями поверх; основная модель — выбранный провайдер.

    Список провайдеров из базы заменяет CQA_PROVIDERS, как любое значение из интерфейса.
    """
    values = dict(overrides)
    stored = values.pop("providers", None)
    s = settings.model_copy(update={k: SecretStr(v) if k in SECRETS else v for k, v in values.items()})
    env = s.providers.get(ENV) or Provider(
        label="Из .env",
        base_url=s.llm_base_url,
        model=s.llm_model,
        profile=s.llm_profile,
        where=s.data_where,
        key=s.llm_api_key,
    )
    known = s.providers if stored is None else {k: Provider.model_validate(v) for k, v in stored.items()}
    providers = {ENV: env, OPENROUTER: openrouter(s)} | known
    main = s.llm_provider if s.llm_provider in providers else ENV
    return s.model_copy(update={"providers": providers, "llm_provider": main, **as_llm(providers[main])})


def provider(settings: Settings, pid: str) -> Provider:
    found = settings.providers.get(pid)
    if found is None:
        raise NotFound(f"Нет провайдера {pid}")
    return found


def config_error(settings: Settings) -> str | None:
    """Ошибка конфигурации; LlmEvaluator бросает её как ConfigError при evaluate, а не при сборке."""
    if settings.evaluator == "jev":  # только Jev: ключ и адрес языковой модели не нужны
        if settings.llm_mode != "replay" and settings.jev_api_key is None:
            return (
                f"Нет ключа Jev для оценки только Jev в режиме {settings.llm_mode}: задайте CQA_JEV_API_KEY"
            )
        return None
    if settings.llm_profile not in PROFILES:
        return f"Неизвестный профиль модели {settings.llm_profile}, допустимы: {', '.join(PROFILES)}"
    if settings.llm_mode != "replay" and settings.llm_api_key is None:
        return f"Нет ключа модели для режима {settings.llm_mode}: задайте CQA_LLM_API_KEY"
    if settings.llm_mode != "replay" and not settings.llm_base_url:
        return f"Нет адреса модели для режима {settings.llm_mode}: задайте CQA_LLM_BASE_URL"
    if settings.verifier == "jev" and settings.llm_mode != "replay" and settings.jev_api_key is None:
        return f"Нет ключа второго мнения для режима {settings.llm_mode}: задайте CQA_JEV_API_KEY"
    if settings.verifier not in (None, "jev"):
        second = settings.providers.get(settings.verifier)
        if second is None:
            return f"Неизвестный провайдер второго мнения {settings.verifier}"
        if settings.llm_mode != "replay" and (second.key is None or not second.base_url):
            return f"Нет ключа или адреса провайдера второго мнения {second.label}"
    return None


def view(settings: Settings) -> dict[str, Any]:
    """`GET /api/config`: всё для формы режима, ключи — только признаком наличия."""
    return {
        "llm_mode": settings.llm_mode,
        "llm_provider": settings.llm_provider,
        "providers": [
            {"id": pid, **p.model_dump(exclude={"key"}), "has_key": p.key is not None}
            for pid, p in settings.providers.items()
        ],
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_profile": settings.llm_profile,
        "profiles": list(PROFILES),
        "has_llm_key": settings.llm_api_key is not None,
        "data_where": settings.data_where,
        "anonymize": settings.anonymize,
        "verifier": settings.verifier,
        "evaluator": settings.evaluator,
        "has_jev_key": settings.jev_api_key is not None,
        "allow_real_data": settings.allow_real_data,
    }


def configure(store: Store, settings: Settings, body: Mapping[str, Any], apply: Apply) -> Settings:
    """Выбрать основную модель и второе мнение, проверить, применить, сохранить. Пустой ключ Jev — прежний.

    `apply` пересобирает оценщик и бросает ошибку конфигурации или `Conflict`; тогда ничего не сохраняется.
    """
    update = {k: v for k, v in body.items() if not (k in SECRETS and not v)}
    if update["llm_provider"] not in settings.providers:
        raise Invalid(f"Нет провайдера {update['llm_provider']}")
    candidate = effective(settings, update)
    error = config_error(candidate)
    if error is not None:
        raise Invalid(error)
    return _commit(store, candidate, update, apply)


def run_settings(settings: Settings, override: Mapping[str, Any]) -> Settings:
    """Режим одного запуска (перепроверка другой моделью или с другими настройками): `override` —
    `evaluator`, `llm_provider`, `verifier` поверх текущего режима. Сохранённый режим не меняется."""
    main, second = override.get("llm_provider"), override.get("verifier")
    if main is not None and main not in settings.providers:
        raise Invalid(f"override.llm_provider: нет провайдера {main}")
    if second not in (None, "jev") and second not in settings.providers:
        raise Invalid(f"override.verifier: нет провайдера {second}")
    candidate = effective(settings, override)
    error = config_error(candidate)
    if error is not None:
        raise Invalid(f"Перепроверка: {error}")
    return candidate


def put_provider(
    store: Store, settings: Settings, pid: str, body: Mapping[str, Any], apply: Apply
) -> Settings:
    """Создать или изменить провайдера; пустой ключ оставляет сохранённый. Ключ не проверяется: его
    отсутствие у основной модели всплывает при оценке, как у `.env`."""
    if pid == ENV:
        raise Invalid("Провайдер env задан в .env: меняйте CQA_LLM_* там")
    if not _ID.fullmatch(pid):
        raise Invalid("Код провайдера: строчная латиница, цифры и дефис, до 32 знаков")
    if pid == OPENROUTER:  # адрес, профиль и место обработки встроенного провайдера не меняются
        preset = openrouter(settings).model_dump(exclude={"key"})
        body = {**preset, "model": body.get("model") or preset["model"], "key": body.get("key")}
    url = urlsplit(str(body.get("base_url") or ""))
    if url.scheme not in ("http", "https") or not url.netloc:
        raise Invalid("Адрес API модели должен начинаться с http:// или https://")
    if body.get("profile") not in PROFILES:
        raise Invalid(f"Неизвестный профиль модели {body.get('profile')}, допустимы: {', '.join(PROFILES)}")
    old = settings.providers.get(pid)
    key = body.get("key") or (old.key.get_secret_value() if old and old.key else None)
    stored = _stored(settings, settings.providers) | {pid: {**body, "key": key}}
    return _commit(store, effective(settings, {"providers": stored}), {"providers": stored}, apply)


def delete_provider(store: Store, settings: Settings, pid: str, apply: Apply) -> Settings:
    provider(settings, pid)
    if pid == settings.llm_provider:
        raise Conflict(f"Провайдер {pid} — основная модель: сначала выберите другую")
    if pid == settings.verifier:
        raise Conflict(f"Провайдер {pid} — второе мнение: сначала выберите другое")
    if pid == ENV:
        raise Conflict("Провайдер из .env удалить нельзя")
    stored = _stored(settings, {k: p for k, p in settings.providers.items() if k != pid})
    return _commit(store, effective(settings, {"providers": stored}), {"providers": stored}, apply)


def _stored(settings: Settings, providers: Mapping[str, Provider]) -> dict[str, dict[str, Any]]:
    """Список для базы без env и неизменённого openrouter-jev (ключ из .env остаётся в .env);
    ключи открытым текстом, как `llm_api_key` в overrides.

    ponytail: изменённый openrouter-jev хранит свой ключ, и новый ключ в .env его не меняет до `DELETE`.
    """
    return {
        k: {**p.model_dump(exclude={"key"}), "key": p.key.get_secret_value() if p.key else None}
        for k, p in providers.items()
        if k != ENV and not (k == OPENROUTER and p == openrouter(settings))
    }


def _commit(store: Store, candidate: Settings, update: Mapping[str, Any], apply: Apply) -> Settings:
    apply(candidate)
    store.set_overrides(update)
    return candidate
