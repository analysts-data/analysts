"""Доступ по токену для показа по сети (CQA_ACCESS_TOKEN): вход /login?token=… кладёт cookie
cqa_access, без неё /api/* — 401 JSON, остальное — страница входа; /api/health открыт.
Клиенты интеграционного API вместо cookie шлют `Authorization: Bearer <token>`; предзапрос CORS
(OPTIONS) проходит без токена — в нём нет данных."""

import hmac
import logging
import re
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "cqa_access"
INGEST = re.compile(r"/api/sources/[^/]+/ingest")
PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>CQA</title></head>
<body style="font:16px system-ui,sans-serif;margin:3rem"><h1>Доступ по ссылке с токеном</h1>
<p>Откройте полную ссылку для входа, её показывает <code>make share</code>.</p></body></html>"""


def _hide_token(record: logging.LogRecord) -> bool:
    """Журнал uvicorn пишет путь с query: значение token= заменяется на ***."""
    if isinstance(record.args, tuple):
        record.args = tuple(
            re.sub(r"token=[^&\s]*", "token=***", a) if isinstance(a, str) else a for a in record.args
        )
    return True


def protect(app: FastAPI, token: str) -> None:
    secret = token.encode()

    def valid(value: str | None) -> bool:
        return value is not None and hmac.compare_digest(value.encode(), secret)

    @app.middleware("http")
    async def access(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        auth = request.headers.get("authorization", "")
        bearer = auth[7:] if auth[:7].lower() == "bearer " else None
        if path == "/login" and valid(request.query_params.get("token")):
            response = RedirectResponse("/", status_code=302)
            response.set_cookie(COOKIE, token, httponly=True, samesite="lax")
            return response
        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            return await call_next(request)
        # webhook источника проверяет свой токен сам (services/sources.py): у внешнего сервиса нет cookie
        open_path = path == "/api/health" or INGEST.fullmatch(path) is not None
        if open_path or (path != "/login" and (valid(request.cookies.get(COOKIE)) or valid(bearer))):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Нужен вход по ссылке с токеном"}, status_code=401)
        return HTMLResponse(PAGE, status_code=401)

    logging.getLogger("uvicorn.access").addFilter(_hide_token)  # the same function is added once
