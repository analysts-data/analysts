"""Service errors; create_app maps them to HTTP codes (design/ports.md)."""


class NotFound(Exception):  # 404
    pass


class Invalid(Exception):  # 422
    pass


class Conflict(Exception):  # 409
    pass


class Upstream(Exception):  # 502
    pass


class Unavailable(Exception):  # 503
    pass


class ConfigError(Exception):  # no HTTP code: raised by evaluate, lands in run errors
    pass
