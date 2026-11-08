"""Метрики использования: белый список событий, очистка props от текста, сводка и CSV. Чистые функции."""

import csv
import io
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any, Literal

from cqa.domain.review import ASTANA

Event = Literal[
    "page_view", "action", "search", "filter", "dialog_open", "appeal_open", "appeal_submit",
    "decision_submit", "checklist_save", "run_start", "export", "report_open", "help_open",
    "error_shown", "time_on_page",
]  # fmt: skip
TOKEN = r"^\w[\w.:/#-]{0,63}$"  # имя экрана, data-act, id: без пробелов, значит не фраза
# props хранятся только из этого списка и только числом, bool или токеном; `q` поиска — длиной
PROPS = frozenset(
    {"act", "id", "cid", "ms", "len", "has_result", "name", "value", "kind", "format", "code", "n"}
)
FUNNELS = (
    ("Открыл диалог → подал апелляцию", "dialog_open", "appeal_submit"),
    ("Открыл апелляцию → принял решение", "appeal_open", "decision_submit"),
)
TOP = 10


@dataclass(frozen=True)
class UsageEvent:
    at: datetime
    actor: str
    role: str | None
    event: str
    page: str
    props: Mapping[str, Any]


def clean_props(props: Mapping[str, Any]) -> dict[str, Any]:
    """Текст диалога и поисковый запрос не сохраняются: от `q` остаётся длина, прочие фразы отбрасываются."""
    out: dict[str, Any] = {}
    for k, v in props.items():
        if k == "q" and isinstance(v, str):
            out["len"] = len(v)
        elif k in PROPS and (
            v is None or isinstance(v, bool | int | float) or (isinstance(v, str) and re.fullmatch(TOKEN, v))
        ):
            out[k] = v
    return out


def funnel(events: Iterable[UsageEvent], frm: str, to: str) -> dict[str, Any]:
    """Пара (сотрудник, props.id) начата событием frm и дошла, если после него было to.

    Время — от последнего frm до первого to: сотрудник мог открыть диалог несколько раз."""
    opened: dict[tuple[str, Any], datetime] = {}
    done: dict[tuple[str, Any], float] = {}
    for e in sorted(events, key=lambda e: e.at):
        key = (e.actor, e.props.get("id"))
        if key in done:
            continue
        if e.event == frm:
            opened[key] = e.at
        elif e.event == to and key in opened:
            done[key] = (e.at - opened[key]).total_seconds()
    started, converted = len(opened), len(done)
    return {
        "started": started,
        "converted": converted,
        "rate": round(converted / started, 3) if started else None,
        "median_s": round(median(done.values()), 1) if done else None,
    }


def _counts(events: Iterable[UsageEvent], event: str, key: str) -> list[dict[str, Any]]:
    found = Counter(str(e.props.get(key, "—")) for e in events if e.event == event)
    return [{key: k, "n": n} for k, n in found.most_common(TOP)]


def aggregate(events: Sequence[UsageEvent]) -> dict[str, Any]:
    users: defaultdict[str, set[str]] = defaultdict(set)
    pages: Counter[str] = Counter()
    views: Counter[str] = Counter()
    ms: defaultdict[str, list[float]] = defaultdict(list)
    errors: Counter[tuple[str, str]] = Counter()
    for e in events:
        users[e.at.astimezone(ASTANA).date().isoformat()].add(e.actor)
        pages[e.page] += 1
        views[e.page] += e.event == "page_view"
        if e.event == "time_on_page" and isinstance(e.props.get("ms"), int | float):
            ms[e.page].append(e.props["ms"])
        if e.event == "error_shown":
            errors[(e.page, str(e.props.get("code", "—")))] += 1
    return {
        "events": len(events),
        "active_users": [{"day": d, "users": len(users[d])} for d in sorted(users)],
        "screens": [
            {"page": p, "events": n, "views": views[p], "median_ms": round(median(ms[p])) if ms[p] else None}
            for p, n in pages.most_common()
        ],
        "actions": _counts(events, "action", "act"),
        "funnels": [{"name": name, **funnel(events, frm, to)} for name, frm, to in FUNNELS],
        "errors": [{"page": p, "code": c, "n": n} for (p, c), n in errors.most_common(TOP)],
        "exports": _counts(events, "export", "kind"),
        "reports": _counts(events, "report_open", "kind"),
    }


def _value(v: Any) -> str:
    return "" if v is None else str(v).replace(".", ",") if isinstance(v, float) else str(v)


def to_csv(usage: Mapping[str, Any]) -> str:
    """Длинная таблица для Excel (BOM, «;»): ключ — строковые поля записи, показатели — числовые."""
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";")
    out.writerow(["Раздел", "Ключ", "Показатель", "Значение"])
    for section, items in usage.items():
        if not isinstance(items, list):
            continue
        for item in items:
            key = " / ".join(v for v in item.values() if isinstance(v, str))
            for metric, v in item.items():
                if not isinstance(v, str):
                    out.writerow([section, key, metric, _value(v)])
    return "﻿" + buf.getvalue()
