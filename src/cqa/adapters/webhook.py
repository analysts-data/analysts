"""Событие запуска на адрес клиента (`CQA_WEBHOOK_URL`): JSON, подпись HMAC-SHA256, сбой — только в журнал.

В событии нет текста диалогов, в журнале — адреса: в нём может быть токен клиента.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from typing import Any

import httpx

log = logging.getLogger("cqa.webhook")


async def send_event(http: httpx.AsyncClient, url: str, secret: str | None, event: Mapping[str, Any]) -> None:
    body = json.dumps(event, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-CQA-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        (await http.post(url, content=body, headers=headers)).raise_for_status()
    except httpx.HTTPError as exc:
        why = (
            f"код {exc.response.status_code}"
            if isinstance(exc, httpx.HTTPStatusError)
            else type(exc).__name__
        )
        log.warning("вебхук %s запуска %s не доставлен: %s", event.get("event"), event.get("run_id"), why)
