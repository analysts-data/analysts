"""HTTP-клиент OpenAI-совместимого API: повторы, лимиты, профили параметров."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from cqa.domain.prompt import Message
from cqa.services.errors import ConfigError
from cqa.services.evaluation import ModelUnavailable, Reply
from cqa.settings import Settings

_RETRY_PAUSES = (5.0, 10.0, 20.0)
_RETRIABLE_4XX = frozenset({429})

PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    # LiteLLM у llm.alem.ai отклоняет незнакомые параметры (thinking); json_object выключает рассуждение
    "plain": {"on": {}, "off": {"response_format": {"type": "json_object"}}},
    "deepseek": {
        "on": {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        "off": {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}},
    },
}


def _error_text(response: httpx.Response) -> str:
    return f"HTTP {response.status_code}: {response.text[:300]}"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def post_json(
    http: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    attempts: int = 4,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    gate: Callable[[], Awaitable[None]] | None = None,
    http_ms: list[float] | None = None,
) -> dict[str, Any]:
    """POST с телом JSON и повторами 429, 5xx, таймаутов и ошибок соединения.

    `gate` проходит каждая попытка (окно лимита запросов), в `http_ms` попадает
    длительность каждого HTTP-вызова без ожидания лимита.
    """
    last_error: str | None = None
    for attempt in range(attempts):
        if gate is not None:
            await gate()
        started = time.monotonic()
        try:
            response = await http.post(url, json=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 == attempts:
                break
            await sleep(_RETRY_PAUSES[attempt])
            continue
        finally:
            if http_ms is not None:
                http_ms.append((time.monotonic() - started) * 1000)
        if response.status_code == 200:
            return response.json()
        if response.status_code not in _RETRIABLE_4XX and response.status_code < 500:
            raise ModelUnavailable(_error_text(response))
        last_error = _error_text(response)
        if attempt + 1 == attempts:
            break
        pause = _retry_after(response)
        if pause is None:
            pause = _RETRY_PAUSES[attempt]
        await sleep(pause)
    raise ModelUnavailable(last_error or "нет ответа провайдера")


class RateLimiter:
    """Скользящее окно 60 секунд на не более `rpm` запросов (`0` — без лимита)."""

    def __init__(
        self,
        rpm: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rpm = rpm
        self._clock = clock
        self._sleep = sleep
        self._window: deque[float] = deque()

    async def acquire(self) -> None:
        if self._rpm <= 0:
            return
        while True:
            now = self._clock()
            while self._window and self._window[0] <= now - 60:
                self._window.popleft()
            if len(self._window) < self._rpm:
                self._window.append(now)
                return
            await self._sleep(self._window[0] + 60 - now)


class ChatClient:
    """Один клиент на процесс: семафор, окно лимита, профиль параметров."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._semaphore = asyncio.Semaphore(settings.llm_max_parallel)
        self._limiter = RateLimiter(settings.llm_rpm)

    async def complete(self, messages: list[Message]) -> Reply:
        profile = PROFILES.get(self._settings.llm_profile)
        if profile is None:
            raise ConfigError(
                f"Неизвестный профиль модели {self._settings.llm_profile}, допустимы: {', '.join(PROFILES)}"
            )
        body: dict[str, Any] = {"model": self._settings.llm_model, "messages": messages}
        body |= profile[self._settings.llm_reasoning]
        # ключа может не быть в replay (кассеты не ходят в сеть); в live отсутствие ключа
        # раньше этого места блокирует LlmEvaluator через config_error
        api_key = self._settings.llm_api_key.get_secret_value() if self._settings.llm_api_key else ""
        headers = {"Authorization": f"Bearer {api_key}"}
        http_ms: list[float] = []
        async with self._semaphore:
            data = await post_json(
                self._http,
                f"{self._settings.llm_base_url}/chat/completions",
                body,
                headers,
                gate=self._limiter.acquire,
                http_ms=http_ms,
            )
        usage = data.get("usage") or {}
        cost = (
            usage.get("prompt_tokens", 0) * self._settings.llm_price_in
            + usage.get("completion_tokens", 0) * self._settings.llm_price_out
        ) / 1_000_000
        return Reply(text=data["choices"][0]["message"]["content"], cost=cost, ms=int(sum(http_ms)))
