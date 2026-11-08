"""Статистика разговора диалога и нормы команды: звонок — из разбора интонации, чат — по меткам."""

from collections.abc import Mapping
from typing import Any

from cqa.adapters.store import Store
from cqa.domain.talkstats import CALL, CHAT, RULE, chat_stats, mark, norms
from cqa.services.errors import NotFound
from cqa.services.ports import DialogSource, Voice
from cqa.services.prosody import dialog_prosody


def team_norms(store: Store) -> dict[str, Any]:
    """Звонки с сохранённым разбором и чаты с ответами оператора, каждый канал отдельно; `operators` —
    то же по диалогам каждого сотрудника (`Dialog.operator`)."""
    talk = {k: b["talk"] for k, b in store.prosodies().items() if "talk" in b}
    rows: list[tuple[str | None, str, Mapping[str, float | None]]] = []
    for d in store.list_dialogs():
        stats = talk.get(d.id) if d.ch == "call" else chat_stats(d.lines or [])
        if stats:
            rows.append((d.operator, d.ch, stats))

    def channels(who: set[str | None]) -> dict[str, Any]:
        pick = {ch: [s for op, c, s in rows if c == ch and op in who] for ch in ("call", "chat")}
        return {"call": norms(pick["call"], CALL), "chat": norms(pick["chat"], CHAT)}

    names = sorted({op for op, _, _ in rows if op})
    team = channels({op for op, _, _ in rows})
    return {"rule": RULE, **team, "operators": {name: channels({name}) for name in names}}


async def dialog_talkstats(
    store: Store, source: DialogSource, voice: Voice, dialog_id: str
) -> dict[str, Any]:
    """404 — неизвестный id, чат без меток ответа, звонок без записи; 502 — запись не получена."""
    dialog = store.get_dialog(dialog_id)
    if dialog is None:
        raise NotFound(f"Диалога {dialog_id} нет")
    if dialog.ch == "chat":
        stats = chat_stats(dialog.lines or [])
        if stats is None:
            raise NotFound(f"В чате {dialog_id} нет ответов оператора с метками времени")
    else:
        body = await dialog_prosody(store, source, voice, dialog_id)
        if "talk" not in body:
            body = await dialog_prosody(store, source, voice, dialog_id, fresh=True)
        stats = body["talk"]
    section = team_norms(store)[dialog.ch]
    return {
        "ch": dialog.ch,
        "rule": RULE,
        "n": section["n"],
        "note": section["note"],
        "metrics": mark(stats, section),
    }
