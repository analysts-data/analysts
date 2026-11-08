"""Run event to the client's address: JSON, HMAC signature, a failure is only logged."""

import hashlib
import hmac
import json
import logging

import httpx
import pytest
import respx

from cqa.adapters.webhook import send_event

URL = "https://crm.test/hooks/cqa?token=t0k"
EVENT = {
    "event": "run.finished",
    "run_id": 7,
    "status": "done",
    "done": 8,
    "total": 8,
    "errors": [],
    "dialog_ids": ["syn-chat-ru"],
}


@respx.mock
async def test_event_is_posted_as_json_with_an_hmac_signature() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        await send_event(http, URL, "s3cret", EVENT)
    request = route.calls.last.request
    assert json.loads(request.content) == EVENT
    assert request.headers["Content-Type"] == "application/json"
    signature = hmac.new(b"s3cret", request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-CQA-Signature"] == f"sha256={signature}"


@respx.mock
async def test_without_a_secret_there_is_no_signature() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as http:
        await send_event(http, URL, None, EVENT)
    assert "X-CQA-Signature" not in route.calls.last.request.headers


@pytest.mark.parametrize(
    "outcome", [httpx.Response(500), httpx.ConnectError("refused")], ids=["status", "network"]
)
async def test_failed_delivery_is_logged_without_the_address_and_does_not_raise(
    outcome: httpx.Response | Exception, caplog: pytest.LogCaptureFixture
) -> None:
    with respx.mock, caplog.at_level(logging.WARNING, "cqa.webhook"):
        route = respx.post(URL)
        if isinstance(outcome, Exception):
            route.mock(side_effect=outcome)
        else:
            route.mock(return_value=outcome)
        async with httpx.AsyncClient() as http:
            await send_event(http, URL, None, EVENT)
    assert "run.finished" in caplog.text and "7" in caplog.text
    assert "t0k" not in caplog.text and "crm.test" not in caplog.text
