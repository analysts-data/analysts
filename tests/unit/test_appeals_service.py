"""Апелляции и решения проверяющего (review-workflow, группа 5, решения 13–15)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Checklist, CriterionResult, Dialog
from cqa.domain.review import fingerprint, stamp
from cqa.services.appeals import file_appeal
from cqa.services.errors import Conflict, Invalid, NotFound

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 11, 7, 10, 10, tzinfo=UTC)
COMMENT = "Срок вывода назван, это существенная часть ответа."


@pytest.fixture
def store() -> Store:
    store = Store(connect(":memory:"))
    store.add_checklist(
        Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text()), "начальная версия"
    )
    dialogs = json.loads((FIXTURES / "dialogs_prototype.json").read_text())
    store.add_dialogs([Dialog.model_validate(d) for d in dialogs if d["id"] in ("call-024", "p1-ru-003")], {})
    return store


def add_result(store: Store, dlg: str, cid: str, **result: Any) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    criterion = next(c for c in checklist.criteria if c.id == cid)
    store.add_result(
        dlg, cid, checklist.version, fingerprint(checklist, criterion), CriterionResult.model_validate(result)
    )


def test_file_appeal_takes_current_answer(store: Store) -> None:
    add_result(store, "p1-ru-003", "04", a=5)

    appeal = file_appeal(
        store, dlg="p1-ru-003", cid="04", ask=10, ev=[8], comment=COMMENT, by="Оператор", now=NOW
    )

    assert appeal.id == "a1"
    assert appeal.kind == "appeal"
    assert appeal.from_ == 5
    assert appeal.ask == 10
    assert appeal.to is None
    assert appeal.status == "pending"
    assert appeal.at == stamp(NOW) == "07.11 15:10"
    assert appeal.ev == [8]
    assert appeal.comment == COMMENT
    assert appeal.by == "Оператор"


def appeal(store: Store, **over: Any):
    args: dict[str, Any] = {
        "dlg": "p1-ru-003",
        "cid": "04",
        "ask": 10,
        "ev": [8],
        "comment": COMMENT,
        "by": "Оператор",
        "now": NOW,
    }
    return file_appeal(store, **(args | over))


@pytest.mark.parametrize(
    ("over", "error", "detail"),
    [
        ({"dlg": "nope"}, NotFound, "Диалог nope не найден"),
        ({"cid": "99"}, NotFound, "Критерия 99 нет в чек-листе v3"),
        ({"cid": "08"}, Invalid, "Флаг нарушения не оспаривается: у критерия 08 нет баллов"),
        ({"cid": "06"}, Invalid, "Критерий 06 ждёт оценки, оспаривать пока нечего"),
        ({"ask": 12}, Invalid, "Ответ 12 недопустим для критерия 04: допустимы 20, 15, 10, 5, 0, na"),
        ({"ask": 5}, Invalid, "Просимый ответ совпадает с текущим"),
        ({"comment": "   "}, Invalid, "Комментарий обязателен: не короче 10 символов"),
    ],
)
def test_file_appeal_refusals(
    store: Store, over: dict[str, Any], error: type[Exception], detail: str
) -> None:
    add_result(store, "p1-ru-003", "04", a=5)

    with pytest.raises(error) as exc:
        appeal(store, **over)

    assert str(exc.value) == detail
    assert store.list_appeals() == []


def test_second_appeal_while_first_is_pending_conflicts(store: Store) -> None:
    add_result(store, "p1-ru-003", "04", a=5)
    appeal(store)

    with pytest.raises(Conflict) as exc:
        appeal(store, ask=15)

    assert str(exc.value) == "По критерию 04 уже есть a1 на рассмотрении"
    assert len(store.list_appeals()) == 1
