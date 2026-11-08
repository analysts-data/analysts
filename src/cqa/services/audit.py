"""Журнал действий: кто, когда, что и над чем сделал. Только дополняется (триггеры в store).

Вызывают все изменяющие пути и выгрузки: `record(store, actor, action, target_type, target_id, details)`.
Поля с key, token, secret, password в `details` отбрасываются на любой глубине: ключи в журнал не попадают.
"""

import csv
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cqa.adapters.store import Store
from cqa.domain.checklist_export import _cell
from cqa.domain.review import ASTANA

ANONYMOUS = "без входа"
SECRET = re.compile(r"key|token|secret|password", re.IGNORECASE)
COLUMNS = ("id", "at", "actor_id", "actor_name", "role", "action", "target_type", "target_id", "details")
AuditFormat = Literal["json", "csv"]


@dataclass(frozen=True)
class Actor:
    """Кто действует. `id` None — без входа: имя — подпись роли из тела запроса, как до журнала."""

    id: str | None
    name: str
    role: str = ""  # operator | qa | reviewer | manager | admin; "" без входа


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _clean(v) for k, v in value.items() if not SECRET.search(str(k))}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def record(
    store: Store,
    actor: Actor,
    action: str,
    target_type: str,
    target_id: object,
    details: Mapping[str, Any] | None = None,
) -> None:
    store.add_audit(
        {
            "at": datetime.now(ASTANA).isoformat(timespec="seconds"),
            "actor_id": actor.id,
            "actor_name": actor.name or ANONYMOUS,
            "role": actor.role,
            "action": action,
            "target_type": target_type,
            "target_id": "" if target_id is None else str(target_id),
            "details": _clean(details or {}),
        }
    )


def audit_log(
    store: Store,
    fmt: AuditFormat,
    *,
    actor: str | None = None,
    action: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]] | str:
    """`GET /api/audit`: новые первыми; csv — UTF-8 с BOM и «;», как экспорт чек-листа."""
    rows = store.audit(actor=actor, action=action, since=since, limit=limit)
    if fmt == "json":
        return rows
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";")
    out.writerow(COLUMNS)
    for row in rows:
        cells = [row[c] for c in COLUMNS[:-1]] + [json.dumps(row["details"], ensure_ascii=False)]
        out.writerow([_cell("" if v is None else str(v)) for v in cells])
    return "\ufeff" + buf.getvalue()
