"""Service errors; create_app maps them to HTTP codes (design/ports.md)."""


class NotFound(Exception):  # 404
    pass


class Invalid(Exception):  # 422
    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or {}  # путь поля ("criteria.4.na") -> текст; в ответе — "fields"


class Conflict(Exception):  # 409
    pass


class Upstream(Exception):  # 502
    pass


class Unavailable(Exception):  # 503
    pass


class ConfigError(Exception):  # no HTTP code: raised by evaluate, lands in run errors
    pass
