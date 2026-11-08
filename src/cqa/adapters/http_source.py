"""HTTP-клиент внешних REST-источников (`http_json`) с защитой от SSRF.

Адрес источника вводит пользователь интерфейса, а запрос уходит с сервера: без проверки им можно
прочитать внутреннюю сеть (метаданные облака 169.254.169.254, админки на localhost). Поэтому адреса
вне публичного интернета запрещены, пока `CQA_ALLOW_PRIVATE_SOURCES=1` не разрешит их явно
(источник в своей сети, демонстрация на ноутбуке). Перенаправления не выполняются: иначе публичный
адрес мог бы увести запрос во внутреннюю сеть.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Final
from urllib.parse import urlsplit

import httpx

from cqa.domain.sources import blocked_ip

TIMEOUT_S: Final = 30.0
MAX_BYTES: Final = 20_000_000

Resolve = Callable[[str], Awaitable[list[str]]]


class SourceFetchError(Exception):
    """Адрес запрещён, сеть, таймаут, перенаправление, статус не 2xx или слишком большой ответ."""


async def resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


class HttpSource:
    def __init__(self, http: httpx.AsyncClient, *, allow_private: bool, resolve: Resolve = resolve) -> None:
        self._http = http
        self._allow_private = allow_private
        self._resolve = resolve

    async def fetch(
        self, url: str, *, method: str = "GET", headers: Mapping[str, str] | None = None
    ) -> bytes:
        """Тело ответа; текст ошибки без адреса и заголовков: в них может быть ключ."""
        host = urlsplit(url).hostname or ""
        if not self._allow_private:
            try:
                ips = await self._resolve(host)
            except OSError:
                raise SourceFetchError(f"адрес {host} не найден") from None
            # ponytail: DNS проверяется до запроса, httpx резолвит заново (DNS rebinding); закрыть —
            # подключаться к проверенному IP с SNI исходного хоста
            if not ips or any(blocked_ip(ip) for ip in ips):
                raise SourceFetchError(
                    f"адрес {host} во внутренней сети: запрещено (CQA_ALLOW_PRIVATE_SOURCES=1 разрешает)"
                )
        try:
            response = await self._http.request(
                method, url, headers=dict(headers or {}), timeout=TIMEOUT_S, follow_redirects=False
            )
        except httpx.TimeoutException:
            raise SourceFetchError(f"источник не ответил за {TIMEOUT_S:.0f} с") from None
        except httpx.HTTPError:
            raise SourceFetchError("источник недоступен") from None
        code = response.status_code
        if 300 <= code < 400:
            raise SourceFetchError(f"источник ответил перенаправлением {code}: укажите конечный адрес")
        if not 200 <= code < 300:
            raise SourceFetchError(f"источник ответил статусом {code}")
        if len(response.content) > MAX_BYTES:  # ponytail: читается целиком; поток — если наборы вырастут
            raise SourceFetchError(f"ответ больше {MAX_BYTES // 1_000_000} МБ")
        return response.content
