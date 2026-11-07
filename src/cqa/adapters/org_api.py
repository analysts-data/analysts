"""HTTP-клиент API организаторов: адрес не попадает ни в журнал, ни в текст ошибок."""

import re
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FETCH_TIMEOUT_S: Final = 30.0

_GROUP_ID_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OrgApiError(Exception):
    """Адрес не задан, сеть, таймаут или статус не 2xx."""


def group_url(template: str, group_id: str) -> str:
    """Заменяет значение `group_id` в адресе, сохраняя остальные параметры и их порядок.

    Плохой `group_id` (не `[A-Za-z0-9_-]{1,64}`) даёт `ValueError`.
    """
    if not _GROUP_ID_RE.fullmatch(group_id):
        raise ValueError(f"недопустимый group_id: {group_id!r}")
    parts = urlsplit(template)
    pairs = [
        (k, group_id if k == "group_id" else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    if not any(k == "group_id" for k, _ in pairs):
        pairs.append(("group_id", group_id))
    return urlunsplit(parts._replace(query=urlencode(pairs)))
