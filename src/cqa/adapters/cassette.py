"""Запись и воспроизведение ответов моделей на уровне транспорта httpx."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import httpx


class CassetteMissing(Exception):
    """В режиме replay нет записи для тела запроса."""


def _key(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _audit(path: Path) -> None:
    """Белый список записей (eval-and-delivery 5.2): make e2e задаёт CQA_CASSETTE_LOG, сервер наследует."""
    if log := os.environ.get("CQA_CASSETTE_LOG"):
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{path.parent.name}/{path.name}\n")


class CassetteTransport(httpx.AsyncBaseTransport):
    """replay — только из файла, record — из файла или в сеть с сохранением, live — в сеть."""

    def __init__(
        self,
        mode: Literal["replay", "record", "live"],
        directory: Path,
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._mode = mode
        self._directory = directory
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        path = self._directory / f"{_key(body)}.json"
        if self._mode != "live" and path.exists():
            _audit(path)
            record = json.loads(path.read_text(encoding="utf-8"))
            response = httpx.Response(record["status"], json=record["response"])
            response.request = request
            return response
        if self._mode == "replay":
            raise CassetteMissing(
                "Режим «Записанные ответы»: для этого запроса нет записанного ответа модели. "
                f"Переключите режим на живую модель или запишите ответы (make record, {path.name})"
            )  # без полного пути: сообщение видит пользователь
        transport = self._inner or httpx.AsyncHTTPTransport()
        response = await transport.handle_async_request(request)
        await response.aread()
        if self._mode == "record" and response.status_code == 200:
            record = {
                "request": body,
                "status": response.status_code,
                "response": response.json(),
            }
            self._directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return response
