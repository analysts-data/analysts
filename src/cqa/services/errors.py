"""Service errors; create_app maps them to HTTP codes (design/ports.md)."""

from typing import Any


class NotFound(Exception):  # 404
    pass


class Invalid(Exception):  # 422; fields — ошибки по полям формы: {"config.url": "…"}
    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or {}


class Unauthorized(Exception):  # 401: неверный токен источника (webhook)
    pass


class Conflict(Exception):  # 409
    def __init__(self, message: str = "", **extra: Any) -> None:
        """`extra` — поля тела ответа рядом с `detail`: какой запуск идёт, его ход и ETA."""
        super().__init__(message)
        self.extra = extra


class Upstream(Exception):  # 502
    pass


class Unavailable(Exception):  # 503
    pass


class ConfigError(Exception):  # no HTTP code: raised by evaluate, lands in run errors
    pass
