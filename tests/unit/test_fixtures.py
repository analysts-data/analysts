"""Фикстуры прототипа: чек-лист `CL0` и все десять синтетических диалогов `D`.

Источник — `design/cqa-v3/index.html`, текст общих правил — раздел «Общие правила чек-листа»
в PLAN.md (в самом `CL0` поля `rules` нет).
"""

import json
from pathlib import Path

from cqa.domain.models import Checklist, Dialog

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf8"))


def test_checklist_fixture_is_valid_contract_checklist() -> None:
    cl = Checklist.model_validate(load_fixture("checklist_v3.json"))

    assert cl.version == 3
    assert cl.sections == [
        "Начало и понимание запроса",
        "Безопасность и решение",
        "Ведение и завершение диалога",
        "Грубые нарушения",
    ]
    assert [c.id for c in cl.criteria] == ["01", "02", "03", "04", "05", "06", "07", "08"]
    # rules — текст общих правил из PLAN.md, в самом CL0 поля нет
    assert cl.rules.startswith("Один чек-лист применяется к чатам и звонкам")
    assert "N/A ставь только там, где он разрешён" in cl.rules


def test_dialogs_fixture_carries_all_ten_prototype_dialogs() -> None:
    raw = load_fixture("dialogs_prototype.json")

    assert isinstance(raw, list)
    assert len(raw) == 10

    dialogs = [Dialog.model_validate(d) for d in raw]
    assert len({d.id for d in dialogs}) == 10
    assert dialogs[0].id == "call-024"
    # у звонка есть длительность и свёрнутые участки, у части чатов расшифровки нет
    assert dialogs[0].ch == "call" and dialogs[0].dur is not None
    assert any(getattr(line, "fold", None) for line in dialogs[0].lines or [])
    assert sum(1 for d in dialogs if d.lines is None) == 6


def test_call_line_time_is_its_start_in_the_recording() -> None:
    """Контракт: у звонка `t` равно `s`, как отдаёт ingest; так время в расшифровке совпадает с плеером."""
    for name in ("dialogs_prototype.json", "state_prototype.json"):
        raw = load_fixture(name)
        dialogs = raw if isinstance(raw, list) else raw["dialogs"]  # type: ignore[index]
        for d in dialogs:
            if d["ch"] == "call":
                assert [ln["t"] for ln in d["lines"] if "n" in ln] == [
                    ln["s"] for ln in d["lines"] if "n" in ln
                ], name
