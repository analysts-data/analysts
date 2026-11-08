"""Service errors; create_app maps them to HTTP codes (design/ports.md)."""

from typing import Any


class NotFound(Exception):  # 404
    pass


class Invalid(Exception):  # 422
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
