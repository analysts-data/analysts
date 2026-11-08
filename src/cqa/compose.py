"""Сборка реализаций портов из `Settings`; без запросов наружу."""

from pathlib import Path

import httpx

from cqa.adapters.cassette import CassetteTransport
from cqa.adapters.jev import JEV_MODEL, JevVerifier
from cqa.adapters.llm import ChatClient
from cqa.adapters.org_api import OrgApi
from cqa.services.evaluation import JevEvaluator, LlmEvaluator, Prosody
from cqa.services.ingest import OrgDialogSource
from cqa.services.llm_config import config_error
from cqa.services.ports import Evaluator
from cqa.settings import Settings

CASSETTES = Path(__file__).resolve().parents[2] / "tests" / "cassettes"  # {llm,jev}/{sha}.json


def build_source(settings: Settings) -> OrgDialogSource:
    url = settings.org_api_url.get_secret_value() if settings.org_api_url else None
    return OrgDialogSource(settings, OrgApi(url, httpx.AsyncClient()))


def _http(settings: Settings, kind: str) -> httpx.AsyncClient:
    """Клиент с записями tests/cassettes/{kind} по CQA_LLM_MODE."""
    return httpx.AsyncClient(
        transport=CassetteTransport(settings.llm_mode, CASSETTES / kind), timeout=settings.llm_timeout_s
    )


def _jev(settings: Settings) -> JevVerifier:
    key = settings.jev_api_key.get_secret_value() if settings.jev_api_key else ""  # в replay ключ не нужен
    return JevVerifier(key, _http(settings, "jev"))


def build_evaluator(settings: Settings, prosody: Prosody | None = None) -> Evaluator:
    """Не бросает и не ходит в сеть: replay и record читают записи, record и live — сеть только при вызове.

    prosody — разбор интонации звонка для блока звука в запросе; None — модель видит только текст.
    """
    if settings.evaluator == "jev":
        return JevEvaluator(
            _jev(settings),
            model_name=JEV_MODEL,
            anonymize=settings.anonymize,
            sends_real_data=settings.llm_mode == "live",
            allow_real_data=settings.allow_real_data,
            config_error=config_error(settings),
            prosody=prosody,
        )
    return LlmEvaluator(
        ChatClient(settings, _http(settings, "llm")),
        model_name=settings.llm_model,
        reasoning=settings.llm_reasoning,
        anonymize=settings.anonymize,
        verifier=_jev(settings) if settings.verifier == "jev" else None,
        sends_real_data=settings.llm_mode == "live",
        allow_real_data=settings.allow_real_data,
        config_error=config_error(settings),
        prosody=prosody,
    )
