"""Апелляции и решения проверяющего (review-workflow, группа 5, решения 13–15).

Фикстуры `store` и `conn` из tests/conftest.py: чек-лист v3, диалоги call-024 и p1-ru-003 без результатов.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import CriterionResult
from cqa.domain.review import fingerprint, stamp
from cqa.services.appeals import decide, file_appeal, record_review
from cqa.services.errors import Conflict, Invalid, NotFound

NOW = datetime(2026, 11, 7, 10, 10, tzinfo=UTC)
COMMENT = "Срок вывода назван, это существенная часть ответа."


def add_result(store: Store, dlg: str, cid: str, **result: Any) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    criterion = next(c for c in checklist.criteria if c.id == cid)
    dialog = store.get_dialog(dlg)
    assert dialog is not None
    fp = fingerprint(checklist, criterion, dialog.ch)
    store.add_result(dlg, cid, checklist.version, fp, CriterionResult.model_validate(result))


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


REASON = "Срок вывода назван полностью"


@pytest.mark.parametrize(
    ("over", "error", "detail"),
    [
        ({"appeal_id": "a999"}, NotFound, "Апелляция a999 не найдена"),
        ({"reason": ""}, Invalid, "Причина решения обязательна: не короче 5 символов"),
        ({"reason": " abc  "}, Invalid, "Причина решения обязательна: не короче 5 символов"),
        ({"reviewer": " "}, Invalid, "Укажите проверяющего"),
        ({"to": 12}, Invalid, "Ответ 12 недопустим для критерия 04: допустимы 20, 15, 10, 5, 0, na"),
    ],
)
def test_decide_refusals_leave_appeal_pending(
    store: Store, over: dict[str, Any], error: type[Exception], detail: str
) -> None:
    add_result(store, "p1-ru-003", "04", a=5)
    appeal(store)
    args: dict[str, Any] = {"appeal_id": "a1", "to": 10, "reason": REASON, "reviewer": "Проверяющий"}

    with pytest.raises(error) as exc:
        decide(store, **(args | over), now=NOW)

    assert str(exc.value) == detail
    stored = store.get_appeal("a1")
    assert stored is not None and stored[0].status == "pending"


def test_na_is_refused_where_criterion_forbids_it(store: Store) -> None:
    add_result(store, "p1-ru-003", "01", a="yes")
    appeal(store, cid="01", ask="no")

    with pytest.raises(Invalid) as exc:
        decide(store, "a1", to="na", reason=REASON, reviewer="Проверяющий", now=NOW)

    assert str(exc.value) == "Ответ na недопустим для критерия 01: допустимы yes, no"


FLAG = {"insult": False, "paid": True, "leak": False}
CLEAR = {"insult": False, "paid": False, "leak": False}


@pytest.mark.parametrize(("to", "status"), [(CLEAR, "changed"), (FLAG, "confirmed")])
def test_flag_appeal_asks_for_every_question_and_decision_sets_flag(
    store: Store, to: dict[str, bool], status: str
) -> None:
    add_result(store, "p1-ru-003", "08", a=FLAG)

    filed = appeal(store, cid="08", ask=CLEAR)
    decided = decide(store, "a1", to=to, reason=REASON, reviewer="Проверяющий", now=NOW)

    assert (filed.from_, filed.ask, filed.status) == (FLAG, CLEAR, "pending")
    assert (decided.to, decided.status) == (to, status)


FLAG_KEYS = "Ответ по флагу 08 — объект с ключами insult, paid, leak и значениями true или false"


@pytest.mark.parametrize(
    "ask",
    [{"insult": True}, CLEAR | {"other": True}, CLEAR | {"paid": 1}, "no", 0],
    ids=["missing-key", "extra-key", "not-bool", "string", "number"],
)
def test_flag_appeal_refuses_answer_without_exactly_flag_questions(store: Store, ask: Any) -> None:
    add_result(store, "p1-ru-003", "08", a=FLAG)

    with pytest.raises(Invalid) as exc:
        appeal(store, cid="08", ask=ask)

    assert str(exc.value) == FLAG_KEYS
    assert store.list_appeals() == []


def test_flag_object_is_refused_for_scored_criterion(store: Store) -> None:
    add_result(store, "p1-ru-003", "04", a=5)

    with pytest.raises(Invalid) as exc:
        appeal(store, ask=CLEAR)

    assert str(exc.value).startswith("Ответ {'insult': False, 'paid': False, 'leak': False} недопустим")


def test_decided_appeal_cannot_be_decided_again(store: Store) -> None:
    add_result(store, "p1-ru-003", "04", a=5)
    appeal(store)
    decide(store, "a1", to=10, reason=REASON, reviewer="Проверяющий", now=NOW)

    with pytest.raises(Conflict) as exc:
        decide(store, "a1", to=5, reason=REASON, reviewer="Проверяющий", now=NOW)

    assert str(exc.value) == "Апелляция a1 уже рассмотрена: changed"


def test_closed_appeal_cannot_be_decided(store: Store) -> None:
    add_result(store, "p1-ru-003", "04", a=5)
    appeal(store)
    store.close_pending_appeals(["04"])

    with pytest.raises(Conflict) as exc:
        decide(store, "a1", to=10, reason=REASON, reviewer="Проверяющий", now=NOW)

    assert str(exc.value) == "Апелляция a1 уже рассмотрена: closed"


def review(store: Store, **over: Any):
    args: dict[str, Any] = {
        "dlg": "call-024",
        "cid": "04",
        "frm": 15,
        "to": 10,
        "reason": "Срок ответа клиенту не назван",
        "reviewer": "Специалист КК",
        "now": NOW,
    }
    return record_review(store, **(args | over))


def test_call_result_is_reviewed_under_the_call_fingerprint(store: Store) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    criteria = [c.model_copy(update={"call": "Уточнение"}) if c.id == "04" else c for c in checklist.criteria]
    store.add_checklist(checklist.model_copy(update={"version": 4, "criteria": criteria}), "уточнение")
    add_result(store, "call-024", "04", a=15, alt=10)
    assert review(store, to=10).status == "changed"


@pytest.mark.parametrize(("to", "status"), [(10, "changed"), (15, "confirmed")])
def test_review_settles_model_disagreement(
    store: Store, conn: sqlite3.Connection, to: int, status: str
) -> None:
    add_result(store, "call-024", "04", a=15, alt=10)
    before = result_rows(conn)

    record = review(store, to=to)

    assert record.id == "a1"
    assert record.kind == "review"
    assert record.status == status
    assert (record.from_, record.to) == (15, to)
    assert record.by == record.reviewer == "Специалист КК"
    assert record.reason == "Срок ответа клиенту не назван"
    assert record.at == record.decidedAt == "07.11 15:10"
    assert record.ev == []
    assert record.comment is None
    assert record.ask is None
    assert "ask" not in record.model_dump(by_alias=True, exclude={"ask"})
    assert store.list_appeals()[0][0] == record
    assert result_rows(conn) == before


def test_review_settles_failed_evidence(store: Store) -> None:
    add_result(store, "call-024", "06", a=7, evFail=True)

    record = review(store, cid="06", frm=7, to=4)

    assert (record.kind, record.status, record.to) == ("review", "changed", 4)


@pytest.mark.parametrize(
    ("over", "error", "detail"),
    [
        ({"dlg": "nope"}, NotFound, "Диалог nope не найден"),
        ({"cid": "99"}, NotFound, "Критерия 99 нет в чек-листе v3"),
        ({"cid": "06"}, Invalid, "Критерий 06 ждёт оценки, оспаривать пока нечего"),
        (
            {"cid": "01", "frm": "yes"},
            Invalid,
            "По критерию 01 модели не расходятся и основание прошло проверку",
        ),
        ({"frm": 10}, Conflict, "Текущий ответ по критерию 04: 15. Обновите страницу."),
        ({"to": 12}, Invalid, "Ответ 12 недопустим для критерия 04: допустимы 20, 15, 10, 5, 0, na"),
        ({"reason": "  "}, Invalid, "Причина решения обязательна: не короче 5 символов"),
        ({"reviewer": ""}, Invalid, "Укажите проверяющего"),
    ],
)
def test_review_refusals(store: Store, over: dict[str, Any], error: type[Exception], detail: str) -> None:
    add_result(store, "call-024", "04", a=15, alt=10)
    add_result(store, "call-024", "01", a="yes")

    with pytest.raises(error) as exc:
        review(store, **over)

    assert str(exc.value) == detail
    assert store.list_appeals() == []


def test_second_review_of_same_pair_conflicts(store: Store) -> None:
    add_result(store, "call-024", "04", a=15, alt=10)
    review(store, to=15)

    with pytest.raises(Conflict) as exc:
        review(store, to=10)

    assert str(exc.value) == "По критерию 04 уже есть решение a1"


def test_review_waits_for_pending_appeal(store: Store) -> None:
    add_result(store, "call-024", "04", a=15, alt=10)
    appeal(store, dlg="call-024", ask=20)

    with pytest.raises(Conflict) as exc:
        review(store)

    assert str(exc.value) == "По критерию 04 уже есть a1 на рассмотрении"


def test_review_checks_disagreement_before_pending_appeal(store: Store) -> None:
    add_result(store, "call-024", "01", a="yes")
    appeal(store, dlg="call-024", cid="01", ask="no")

    with pytest.raises(Invalid) as exc:
        review(store, cid="01", frm="yes", to="no")

    assert str(exc.value) == "По критерию 01 модели не расходятся и основание прошло проверку"
