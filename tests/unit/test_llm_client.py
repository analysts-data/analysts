"""post_json и RateLimiter: повторы при перегрузке и лимит запросов в минуту."""

import httpx
import respx

from cqa.adapters.llm import ModelUnavailable, RateLimiter, post_json

URL = "https://llm.example/v1/chat/completions"
KEY = "sk-secret-key-0123456789"
HEADERS = {"Authorization": f"Bearer {KEY}"}


async def _pauses() -> tuple[list[float], object]:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    return waits, sleep


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
