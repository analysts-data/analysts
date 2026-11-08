"""Исходящие события на `CQA_WEBHOOK_URL`: JSON `{event, data}`, подпись HMAC-SHA256 в `X-CQA-Signature`."""

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

log = logging.getLogger(__name__)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def send(
    client: httpx.AsyncClient, url: str, secret: str | None, event: str, items: Sequence[Mapping[str, Any]]
) -> None:
    """Одно событие на каждый элемент. Сбой получателя пишется в журнал и ничего не останавливает."""
    for data in items:
        body = json.dumps({"event": event, "data": data}, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-CQA-Signature"] = sign(secret, body)
        try:
            (await client.post(url, content=body, headers=headers)).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("вебхук %s не доставлен: %s", event, exc)
