"""Режим оценки из интерфейса: адрес и ключ модели, место обработки, обезличивание, второе мнение, звонки.

Значения хранятся в базе поверх `.env` и применяются без перезапуска. Ключи в ответы не попадают.
"""

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from cqa.adapters.llm import PROFILES
from cqa.adapters.store import Store
from cqa.services.errors import Invalid
from cqa.settings import Settings

SECRETS = ("llm_api_key", "jev_api_key")


def effective(settings: Settings, overrides: Mapping[str, Any]) -> Settings:
    """`settings` с сохранёнными из интерфейса значениями поверх."""
    return settings.model_copy(update={k: SecretStr(v) if k in SECRETS else v for k, v in overrides.items()})


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
    return None


def view(settings: Settings) -> dict[str, Any]:
    """`GET /api/config`: всё для формы режима, ключи — только признаком наличия."""
    return {
        "llm_mode": settings.llm_mode,
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


def configure(
    store: Store, settings: Settings, body: Mapping[str, Any], apply: Callable[[Settings], None]
) -> Settings:
    """Проверить, применить и сохранить. Пустой ключ оставляет прежний.

    `apply` пересобирает оценщик и бросает ошибку конфигурации или `Conflict`; тогда ничего не сохраняется.
    """
    update = {k: v for k, v in body.items() if not (k in SECRETS and not v)}
    url = urlsplit(str(update.get("llm_base_url") or ""))
    if url.scheme not in ("http", "https") or not url.netloc:
        raise Invalid("Адрес API модели должен начинаться с http:// или https://")
    candidate = effective(settings, update)
    error = config_error(candidate)
    if error is not None:
        raise Invalid(error)
    apply(candidate)
    store.set_overrides(update)
    return candidate
