"""Промпт оценки по одному критерию: отрисовка диалога и сообщения модели (design.md, п. 2–6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cqa.domain.models import Dialog

_UNRATED = {"internal", "after"}
_SAFE = str.maketrans("<>", "‹›")


def _clock(t: str) -> int | None:
    """Секунды из времени чата ММ:СС; неразобранное — None."""
    try:
        sec = 0
        for part in t.split(":"):
            sec = sec * 60 + int(part)
    except ValueError:
        return None
    return sec


def render_dialog(dialog: Dialog) -> str:
    rows: list[str] = []
    prev: int | None = None
    for item in dialog.lines or []:
        if getattr(item, "fold", False):
            label = item.label.translate(_SAFE)
            rows.append(f"— реплики {item.from_}–{item.to}: {label}, не оценивается —")
            continue
        head = [str(item.n)]
        sec: int | None = None
        if isinstance(item.t, str):
            head.append(item.t)
            sec = _clock(item.t)
        elif item.t is not None:
            sec = int(item.t)
            head.append(f"{sec // 60:02d}:{sec % 60:02d}")
        if sec is not None:
            if prev is not None and sec >= prev:
                head.append(f"+{(sec - prev) // 60}:{(sec - prev) % 60:02d}")
            prev = sec
        who = f"{item.who} · не оценивается" if item.seg in _UNRATED else item.who
        rows.append(f"[{' · '.join(head)}] {who}: {item.text.translate(_SAFE)}")
    return "\n".join(rows)
