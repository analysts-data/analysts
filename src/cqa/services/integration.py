"""Интеграционный API: диалог в формате организаторов или текстом → сохранение и оценка обычным запуском.

Сохранение идёт тем же путём, что «Загрузить JSON» и вставка текста, оценка — `Runner.start`:
запрет реальных звонков и обезличивание остаются в оценщике, второго оценщика нет.
"""

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cqa.adapters.store import Store
from cqa.domain.results import to_results
from cqa.domain.review import effective_answer
from cqa.domain.scoring import total
from cqa.services.datasets import logged
from cqa.services.dialogs import paste_text
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.ports import DialogSource
from cqa.services.runs import Runner
from cqa.services.state import current_state

API = "api"  # встроенный источник интеграционного API (раздел контракта «Источники диалогов»)
CODES = Path(__file__).resolve().parents[3] / "results" / "criteria_map.json"  # как у scripts/results.py
TEAM = "analysts"  # team_name файла результатов, как у scripts/results.py
WAIT_S = 120.0
POLL_S = 0.1


def save(store: Store, source: DialogSource, items: Sequence[Mapping[str, Any]]) -> list[str]:
    """Запись организаторов (`conversation_id`) или вставка (`text`, `ch`, `title`) → id диалога.

    Запись с уже известным id диалог не заменяет. ponytail: пакет не атомарен — 422 на элементе n
    оставляет сохранёнными элементы до него; повтор записей безопасен, вставка создаст новый `paste-<n>`.
    """
    ids = []
    for item in items:
        if "conversation_id" in item:
            envelope = {"isSuccess": True, "data": {"dataset_group_id": API, "records": [dict(item)]}}
            result = source.upload(json.dumps(envelope, ensure_ascii=False).encode())
            if result.errors:
                raise Invalid("; ".join(result.errors))
            with logged(store, API) as keep:  # учёт источников: строка журнала источника «api»
                keep(result)
            ids.append(result.dialogs[0].id)
        else:
            title, ch, text = item.get("title", ""), item["ch"], item["text"]
            ids.append(paste_text(store, title=title, ch=ch, text=text, source_id=API))
    return ids


async def finished(runner: Runner, run_id: int) -> bool:
    """Ждать конца запуска не дольше WAIT_S; False — ещё идёт, клиент продолжит опросом."""
    deadline = time.monotonic() + WAIT_S
    while runner.progress(run_id)["status"] == "running":
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_S)
    return True


def dialog_result(store: Store, dialog_id: str) -> dict[str, Any]:
    """Диалог с текущими `res`, итог и грубая ошибка с учётом решений, запись JSON 1.0 организаторов."""
    # ponytail: всё состояние ради одного диалога; запрос по id, если наборы вырастут до тысяч
    checklist, dialogs, appeals = current_state(store)
    dialog = next((d for d in dialogs if d.id == dialog_id), None)
    if dialog is None:
        raise NotFound(f"Диалог {dialog_id} не найден")
    mine = [a for a in appeals if a.dlg == dialog_id]
    answers = {cid: effective_answer(r, [a for a in mine if a.cid == cid]) for cid, r in dialog.res.items()}
    codes = json.loads(CODES.read_text(encoding="utf-8"))
    try:
        record = to_results([dialog_id], {dialog_id: dialog}, checklist, mine, codes, team="", model={})
    except ValueError:  # карта кодов организаторов не подходит к изменённому чек-листу
        record = None
    return {
        "dialog_id": dialog_id,
        "total": total(checklist, answers),
        "critical_flag": any(isinstance(a, dict) and any(a.values()) for a in answers.values()),
        "criteria": [
            {"cid": c.id, "name": c.name, **dialog.res[c.id].model_dump(mode="json")}
            for c in checklist.criteria
            if c.id in dialog.res
        ],
        "results_v1": record["results"][0] if record else None,
        "dialog": dialog.model_dump(mode="json", exclude_none=True),
    }


def results_doc(store: Store, ids: Sequence[str] | None, model: Mapping[str, str]) -> dict[str, Any]:
    """Файл результатов JSON 1.0 по `ids` в их порядке (None — все диалоги); не оценённый — `error`."""
    checklist, dialogs, appeals = current_state(store)
    codes = json.loads(CODES.read_text(encoding="utf-8"))
    chosen = list(dict.fromkeys(ids)) if ids else [d.id for d in dialogs]
    try:
        return to_results(
            chosen, {d.id: d for d in dialogs}, checklist, appeals, codes, team=TEAM, model=model
        )
    except ValueError as exc:  # карта кодов организаторов не подходит к изменённому чек-листу
        raise Conflict(str(exc)) from None
