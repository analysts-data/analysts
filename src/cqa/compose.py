"""Сборка реализаций портов из `Settings`; без запросов наружу."""

from pathlib import Path

import httpx

from cqa.adapters.cassette import CassetteTransport
from cqa.adapters.llm import PROFILES, ChatClient
from cqa.adapters.org_api import OrgApi
from cqa.services.evaluation import LlmEvaluator, Verifier
from cqa.services.ingest import OrgDialogSource
from cqa.settings import Settings

CASSETTES = Path(__file__).resolve().parents[2] / "tests" / "cassettes"  # {llm,jev}/{sha}.json


def build_source(settings: Settings) -> OrgDialogSource:
    url = settings.org_api_url.get_secret_value() if settings.org_api_url else None
    return OrgDialogSource(settings, OrgApi(url, httpx.AsyncClient()))


def _config_error(settings: Settings) -> str | None:
    """Ошибка конфигурации; LlmEvaluator бросает её как ConfigError при evaluate, а не при сборке."""
    if settings.llm_profile not in PROFILES:
        return f"Неизвестный профиль модели {settings.llm_profile}, допустимы: {', '.join(PROFILES)}"
    if settings.llm_mode != "replay" and settings.llm_api_key is None:
        return f"Нет ключа модели для режима {settings.llm_mode}: задайте CQA_LLM_API_KEY"
    if settings.llm_mode != "replay" and not settings.llm_base_url:
        return f"Нет адреса модели для режима {settings.llm_mode}: задайте CQA_LLM_BASE_URL"
    if settings.verifier == "jev":
        # стык: JevVerifier (llm-evaluation, группа 6) заменяет эту строку и _verifier
        return "Второе мнение Jev ещё не подключено: оставьте CQA_VERIFIER пустым"
    return None


def _verifier(settings: Settings, http: httpx.AsyncClient) -> Verifier | None:
    return None  # CQA_VERIFIER=jev → JevVerifier(settings.jev_api_key, http) после слияния группы 6


def build_evaluator(settings: Settings) -> LlmEvaluator:
    """Не бросает и не ходит в сеть: replay и record читают записи, record и live — сеть только при вызове."""
    http = httpx.AsyncClient(
        transport=CassetteTransport(settings.llm_mode, CASSETTES / "llm"), timeout=settings.llm_timeout_s
    )
    return LlmEvaluator(
        ChatClient(settings, http),
        model_name=settings.llm_model,
        reasoning=settings.llm_reasoning,
        anonymize=settings.anonymize,
        verifier=_verifier(settings, http),
        sends_real_data=settings.llm_mode == "live",
        allow_real_data=settings.allow_real_data,
        config_error=_config_error(settings),
    )
