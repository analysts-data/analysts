"""Клиент модели: post_json, RateLimiter, профили ChatClient и лимиты."""

import asyncio
import json

import httpx
import respx
from pydantic import SecretStr

from cqa.adapters.llm import ChatClient, ModelUnavailable, RateLimiter, post_json
from cqa.services.errors import ConfigError
from cqa.settings import Settings

URL = "https://llm.example/v1/chat/completions"
BASE = "https://llm.example/v1"
KEY = "sk-secret-key-0123456789"
HEADERS = {"Authorization": f"Bearer {KEY}"}


async def _pauses() -> tuple[list[float], object]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    return waits, sleep


# --- post_json (задача 3.4) ---


async def test_post_json_returns_body_of_200():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(200, json={"ok": True})
        waits, sleep = await _pauses()
        async with httpx.AsyncClient() as http:
            data = await post_json(http, URL, {"model": "m"}, HEADERS, sleep=sleep)
    assert data == {"ok": True}
    assert route.call_count == 1
    assert waits == []


async def test_post_json_retries_429_with_retry_after():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "slow down"}),
                httpx.Response(200, json={"ok": 1}),
            ]
        )
        waits, sleep = await _pauses()
        async with httpx.AsyncClient() as http:
            data = await post_json(http, URL, {"model": "m"}, HEADERS, sleep=sleep)
    assert data == {"ok": 1}
    assert route.call_count == 2
    assert waits == [2.0]


async def test_post_json_gives_up_after_four_503():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(503, text="service unavailable")
        waits, sleep = await _pauses()
        async with httpx.AsyncClient() as http:
            try:
                await post_json(http, URL, {"model": "m"}, HEADERS, sleep=sleep)
            except ModelUnavailable as exc:
                message = str(exc)
            else:
                raise AssertionError("ожидали ModelUnavailable")
    assert route.call_count == 4
    assert waits == [5.0, 10.0, 20.0]
    assert "503" in message
    assert KEY not in message


async def test_post_json_does_not_retry_400():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(400, json={"error": "unknown parameter thinking"})
        waits, sleep = await _pauses()
        async with httpx.AsyncClient() as http:
            try:
                await post_json(http, URL, {"model": "m"}, HEADERS, sleep=sleep)
            except ModelUnavailable as exc:
                message = str(exc)
            else:
                raise AssertionError("ожидали ModelUnavailable")
    assert route.call_count == 1
    assert waits == []
    assert "400" in message
    assert "unknown parameter thinking" in message


async def test_post_json_retries_timeout_then_succeeds():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).mock(
            side_effect=[httpx.TimeoutException("timed out"), httpx.Response(200, json={"ok": 2})]
        )
        waits, sleep = await _pauses()
        async with httpx.AsyncClient() as http:
            data = await post_json(http, URL, {"model": "m"}, HEADERS, sleep=sleep)
    assert data == {"ok": 2}
    assert route.call_count == 2
    assert waits == [5.0]


async def test_post_json_exhausts_attempts_on_timeouts():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).mock(side_effect=httpx.TimeoutException("timed out"))
        waits, sleep = await _pauses()
        async with httpx.AsyncClient() as http:
            try:
                await post_json(http, URL, {"model": "m"}, HEADERS, sleep=sleep)
            except ModelUnavailable as exc:
                message = str(exc)
            else:
                raise AssertionError("ожидали ModelUnavailable")
    assert route.call_count == 4
    assert waits == [5.0, 10.0, 20.0]
    assert "TimeoutException" in message


# --- RateLimiter (задача 3.5) ---


class FakeClock:
    """Часы, которые двигает подменённый sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_rate_limiter_holds_fourth_request_until_window_ends():
    clock = FakeClock()
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.now += seconds

    limiter = RateLimiter(3, clock=clock, sleep=sleep)
    for _ in range(3):
        await limiter.acquire()
    assert waits == []

    await limiter.acquire()
    assert waits == [60.0]
    assert clock.now == 60.0


async def test_rate_limiter_without_limit_does_not_wait():
    clock = FakeClock()
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.now += seconds

    limiter = RateLimiter(0, clock=clock, sleep=sleep)
    for _ in range(10):
        await limiter.acquire()
    assert waits == []


# --- ChatClient (задачи 3.2, 3.5) ---

MSGS = [{"role": "system", "content": "промпт"}, {"role": "user", "content": "диалог"}]


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"llm_base_url": BASE, "llm_api_key": SecretStr(KEY)}
    values |= overrides
    return Settings(_env_file=None, **values)


def _ok(content: str = "ответ") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10000, "completion_tokens": 2000},
    }


async def test_complete_plain_on_sends_only_model_and_messages():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(200, json=_ok())
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_reasoning="on"), http)
            reply = await client.complete(MSGS)
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {"model": "qwen3-6", "messages": MSGS}
    assert reply.text == "ответ"
    assert reply.ms >= 0


async def test_complete_plain_off_adds_json_object_response_format():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(200, json=_ok())
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_reasoning="off"), http)
            await client.complete(MSGS)
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "model": "qwen3-6",
        "messages": MSGS,
        "response_format": {"type": "json_object"},
    }


async def test_complete_deepseek_on_enables_thinking():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(200, json=_ok())
        async with httpx.AsyncClient() as http:
            client = ChatClient(
                _settings(llm_profile="deepseek", llm_reasoning="on", llm_model="deepseek-v4-pro"),
                http,
            )
            await client.complete(MSGS)
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "model": "deepseek-v4-pro",
        "messages": MSGS,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
    }


async def test_complete_deepseek_off_disables_thinking_and_forces_json():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL).respond(200, json=_ok())
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_profile="deepseek", llm_reasoning="off"), http)
            await client.complete(MSGS)
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "model": "qwen3-6",
        "messages": MSGS,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }


async def test_complete_costs_by_usage_and_prices():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).respond(200, json=_ok())
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_price_in=0.435, llm_price_out=0.87), http)
            reply = await client.complete(MSGS)
    assert reply.cost == 0.00609


async def test_complete_costs_zero_without_prices_or_usage():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).respond(200, json=_ok())
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_price_in=0.0, llm_price_out=0.0), http)
            zero_prices = await client.complete(MSGS)
    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).respond(200, json={"choices": [{"message": {"content": "без usage"}}]})
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_price_in=0.435, llm_price_out=0.87), http)
            no_usage = await client.complete(MSGS)
    assert zero_prices.cost == 0.0
    assert no_usage.cost == 0.0


async def test_complete_rejects_unknown_profile_before_any_request():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(URL)
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_profile="gemini"), http)
            try:
                await client.complete(MSGS)
            except ConfigError as exc:
                message = str(exc)
            else:
                raise AssertionError("ожидали ConfigError")
    assert "plain, deepseek" in message
    assert route.call_count == 0


async def test_complete_keeps_at_most_max_parallel_in_flight():
    in_flight = 0
    peak = 0

    async def slow_answer(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json=_ok())

    with respx.mock(assert_all_called=False) as mock:
        mock.post(URL).mock(side_effect=slow_answer)
        async with httpx.AsyncClient() as http:
            client = ChatClient(_settings(llm_max_parallel=2), http)
            replies = await asyncio.gather(*(client.complete(MSGS) for _ in range(6)))
    assert [reply.text for reply in replies] == ["ответ"] * 6
    assert peak == 2
