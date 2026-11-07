"""HTTP-клиент OpenAI-совместимого API: повторы, лимиты, профили параметров."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

_RETRY_PAUSES = (5.0, 10.0, 20.0)
_RETRIABLE_4XX = frozenset({429})


class ModelUnavailable(Exception):
    """Провайдер не ответил или вернул ошибку после всех повторов."""


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
) -> dict[str, Any]:
    """POST с телом JSON и повторами 429, 5xx, таймаутов и ошибок соединения."""
    last_error: str | None = None
    for attempt in range(attempts):
        try:
            response = await http.post(url, json=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 == attempts:
                break
            await sleep(_RETRY_PAUSES[attempt])
            continue
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
