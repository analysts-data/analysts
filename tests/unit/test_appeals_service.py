"""Апелляции и решения проверяющего (review-workflow, группа 5, решения 13–15)."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cqa.adapters.store import Store, connect
from cqa.domain.models import Checklist, CriterionResult, Dialog
from cqa.domain.review import fingerprint, stamp
from cqa.services.appeals import decide, file_appeal
from cqa.services.errors import Conflict, Invalid, NotFound

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 11, 7, 10, 10, tzinfo=UTC)
COMMENT = "Срок вывода назван, это существенная часть ответа."


@pytest.fixture
def conn() -> sqlite3.Connection:
    return connect(":memory:")


@pytest.fixture
def store(conn: sqlite3.Connection) -> Store:
    store = Store(conn)
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


def result_rows(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [tuple(r) for r in conn.execute("SELECT dialog_id, cid, body FROM results ORDER BY id")]


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


@pytest.mark.parametrize(("to", "status"), [(10, "changed"), (5, "confirmed")])
def test_decide_records_decision_and_keeps_result(
    store: Store, conn: sqlite3.Connection, to: int, status: str
) -> None:
    add_result(store, "p1-ru-003", "04", a=5)
    before = result_rows(conn)
    appeal(store)
    later = datetime(2026, 11, 7, 11, 5, tzinfo=UTC)

    decided = decide(
        store, "a1", to=to, reason="  Срок вывода назван полностью  ", reviewer="Проверяющий", now=later
    )

    assert decided.id == "a1"
    assert decided.status == status
    assert decided.to == to
    assert decided.reason == "Срок вывода назван полностью"
    assert decided.reviewer == "Проверяющий"
    assert decided.decidedAt == stamp(later) == "07.11 16:05"
    assert decided.from_ == 5
    assert decided.ask == 10
    stored = store.get_appeal("a1")
    assert stored is not None and stored[0] == decided
    assert result_rows(conn) == before
    assert len(before) == 1


def test_new_appeal_after_changed_decision_starts_from_decision(store: Store) -> None:
    add_result(store, "p1-ru-003", "04", a=5)
    appeal(store)
    decide(store, "a1", to=10, reason="Срок вывода назван полностью", reviewer="Проверяющий", now=NOW)

    second = appeal(store, ask=15)

    assert second.id == "a2"
    assert second.from_ == 10
