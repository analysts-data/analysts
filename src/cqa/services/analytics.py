"""GET /api/analytics/<name>: расширенная аналитика из того же состояния, что GET /api/state."""

from datetime import datetime
from typing import Any

from cqa.adapters.jev import JEV_MODEL
from cqa.adapters.store import Store
from cqa.domain.analytics import BY, Filters, build
from cqa.domain.review import ASTANA
from cqa.services.answers import MANUAL
from cqa.services.errors import Invalid
from cqa.services.state import current_state


def analytics(store: Store, name: str, filters: Filters, by: str | None, now: datetime) -> dict[str, Any]:
    if by is not None and by not in BY.get(name, ()):
        allowed = ", ".join(BY.get(name, ())) or "нет"
        raise Invalid(f"Разбивка by={by} не подходит к {name}: допустимы {allowed}")
    checklist, dialogs, appeals = current_state(store)
    today = now.astimezone(ASTANA).date()
    return build(
        name, checklist, dialogs, appeals, today=today, filters=filters, by=by, jev=JEV_MODEL, manual=MANUAL
    )
