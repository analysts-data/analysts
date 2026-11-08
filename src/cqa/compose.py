"""Сборка реализаций портов из `Settings`; без запросов наружу."""

from functools import partial
from pathlib import Path
from typing import Any

import httpx

from cqa.adapters.cassette import CassetteTransport
from cqa.adapters.jev import JEV_MODEL, JevVerifier
from cqa.adapters.llm import ChatClient, ping
from cqa.adapters.org_api import OrgApi
from cqa.adapters.store import Store
from cqa.domain.routing import DEFAULT, Rule
from cqa.services.errors import Invalid
from cqa.services.evaluation import ChatVerifier, JevEvaluator, LlmEvaluator, Prosody, Verifier
from cqa.services.ingest import OrgDialogSource
from cqa.services.llm_config import as_llm, config_error
from cqa.services.ports import Evaluator
from cqa.services.routing import RoutedEvaluator, facts, rule_settings, rules
from cqa.settings import Provider, Settings

CASSETTES = Path(__file__).resolve().parents[2] / "tests" / "cassettes"  # {llm,jev}/{sha}.json
CHECK_TIMEOUT_S = 20


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


def _verifier(settings: Settings) -> Verifier | None:
    if settings.verifier == "jev":
        return _jev(settings)
    second = settings.providers.get(settings.verifier or "")
    if second is None:
        return None
    return ChatVerifier(ChatClient(settings.model_copy(update=as_llm(second)), _http(settings, "llm")))


async def check_provider(provider: Provider) -> dict[str, Any]:
    """Проверка связи мимо записей: синтетический запрос сразу в сеть, реальные данные не уходят."""
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as http:
        return await ping(http, provider)


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
        verifier=_verifier(settings),
        sends_real_data=settings.llm_mode == "live",
        allow_real_data=settings.allow_real_data,
        config_error=config_error(settings),
        prosody=prosody,
    )


def _for_rule(settings: Settings, rule: Rule, prosody: Prosody | None) -> Evaluator | str:
    try:
        s = rule_settings(settings, rule.use)
    except Invalid as exc:  # провайдер удалён после сохранения правила: падают только диалоги правила
        return str(exc)
    return build_evaluator(s, None if rule.use.prosody is False else prosody)


def build_routed(settings: Settings, prosody: Prosody | None, store: Store) -> Evaluator:
    """Оценщик по правилам обработки. Без включённых правил — ровно `build_evaluator`: те же запросы.

    ponytail: у каждого правила свой ChatClient со своим лимитом CQA_LLM_RPM; общий лимит на провайдера,
    если правила с одним провайдером упрутся в его квоту.
    """
    default = build_evaluator(settings, prosody)
    found = rules(settings)
    active = [r for r in found if r.enabled and r.id != DEFAULT]
    if not active:
        return default
    built = {r.id: _for_rule(settings, r, prosody) for r in active}
    return RoutedEvaluator(found, default, built, partial(facts, store))
