"""Коды причин решений и доля ответов, изменённых людьми (eval-and-delivery, reason-codes).

Фикстура `store` из tests/conftest.py: чек-лист v3, диалоги call-024 и p1-ru-003 без результатов.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.appeal_stats import MANUAL, appeal_stats
from cqa.domain.models import Appeal, CriterionResult, ReasonCode
from cqa.domain.review import fingerprint
from cqa.services.appeals import REASONS, decide, file_appeal, reasons, record_review, save_reasons
from cqa.services.errors import Invalid
from fakes import prototype_checklist, prototype_dialogs

NOW = datetime(2026, 11, 8, 6, 0, tzinfo=UTC)
COMMENT = "Срок вывода назван, это существенная часть ответа."
REASON = "Срок вывода назван полностью"


def add_result(store: Store, dlg: str, cid: str, **result: Any) -> None:
    checklist = store.current_checklist()
    assert checklist is not None
    criterion = next(c for c in checklist.criteria if c.id == cid)
    dialog = store.get_dialog(dlg)
    assert dialog is not None
    fp = fingerprint(checklist, criterion, dialog.ch)
    store.add_result(dlg, cid, checklist.version, fp, CriterionResult.model_validate(result))


def filed(store: Store) -> Appeal:
    add_result(store, "p1-ru-003", "04", a=5)
    return file_appeal(
        store, dlg="p1-ru-003", cid="04", ask=10, ev=[8], comment=COMMENT, by="Оператор", now=NOW
    )


def test_catalogue_is_seeded_until_saved(store: Store) -> None:
    labels = [r.label for r in reasons(store)]

    assert labels == [
        "Модель неверно поняла реплику",
        "Не учтён контекст диалога",
        "Критерий сформулирован неоднозначно",
        "Ошибка распознавания речи",
        "Нарушение подтверждено",
        "Оценка верна по регламенту",
        "Другое",
    ]
    assert reasons(store) == REASONS


def test_saved_catalogue_replaces_seed_and_survives_reconnect(store: Store) -> None:
    mine = [ReasonCode(code="script", label="  Нарушен скрипт  ", applies="confirmed")]

    saved = save_reasons(store, mine)

    assert saved == [ReasonCode(code="script", label="Нарушен скрипт", applies="confirmed")]
    assert reasons(store) == saved


@pytest.mark.parametrize(
    ("items", "detail"),
    [
        ([], "Нужна хотя бы одна причина"),
        (
            [{"code": "Bad code", "label": "x", "applies": "both"}],
            "Код причины «Bad code»: строчная латиница, цифры, _ и -, до 32 знаков",
        ),
        ([{"code": "x", "label": "  ", "applies": "both"}], "У причины x нет названия"),
        (
            [{"code": "x", "label": "а", "applies": "both"}, {"code": "x", "label": "б", "applies": "both"}],
            "Код причины x повторяется",
        ),
    ],
)
def test_catalogue_refusals(store: Store, items: list[dict[str, str]], detail: str) -> None:
    with pytest.raises(Invalid) as err:
        save_reasons(store, [ReasonCode.model_validate(i) for i in items])

    assert str(err.value) == detail
    assert reasons(store) == REASONS


def test_decision_keeps_reason_code(store: Store) -> None:
    appeal = filed(store)

    decided = decide(store, appeal.id, to=10, reason=REASON, reviewer="Р", reason_code="misread", now=NOW)

    assert decided.reason_code == "misread"
    stored = store.get_appeal(appeal.id)
    assert stored is not None and stored[0].reason_code == "misread"


def test_decision_without_reason_code_keeps_working(store: Store) -> None:
    appeal = filed(store)

    decided = decide(store, appeal.id, to=10, reason=REASON, reviewer="Р", now=NOW)
    empty = decide(store, filed_again(store).id, to=5, reason=REASON, reviewer="Р", reason_code="", now=NOW)

    assert (decided.reason_code, empty.reason_code) == (None, None)


def filed_again(store: Store) -> Appeal:
    return file_appeal(
        store, dlg="p1-ru-003", cid="04", ask=5, ev=[8], comment=COMMENT, by="Оператор", now=NOW
    )


@pytest.mark.parametrize(
    ("to", "code", "detail"),
    [
        (
            10,
            "nope",
            "Неизвестный код причины nope: допустимы misread, context, ambiguous, asr, violation, "
            "by_rules, other",
        ),
        (10, "by_rules", "Причина «Оценка верна по регламенту» не подходит к решению «оценка изменена»"),
        (5, "misread", "Причина «Модель неверно поняла реплику» не подходит к решению «оценка оставлена»"),
    ],
)
def test_reason_code_must_be_in_catalogue_and_fit_outcome(
    store: Store, to: int, code: str, detail: str
) -> None:
    appeal = filed(store)

    with pytest.raises(Invalid) as err:
        decide(store, appeal.id, to=to, reason=REASON, reviewer="Р", reason_code=code, now=NOW)

    assert str(err.value) == detail
    stored = store.get_appeal(appeal.id)
    assert stored is not None and stored[0].status == "pending"


def test_review_keeps_reason_code_and_checks_it(store: Store) -> None:
    add_result(store, "call-024", "04", a=15, alt=10)
    args: dict[str, Any] = {"dlg": "call-024", "cid": "04", "frm": 15, "reason": REASON, "reviewer": "Р"}

    with pytest.raises(Invalid):
        record_review(store, **args, to=15, reason_code="asr", now=NOW)
    record = record_review(store, **args, to=15, reason_code="by_rules", now=NOW)

    assert (record.status, record.reason_code) == ("confirmed", "by_rules")
    assert [a.id for a, _ in store.list_appeals()] == [record.id]


# --- appeal_stats: чистая функция ---

CHECKLIST = prototype_checklist()
BASE = {d.id: d for d in prototype_dialogs()}["p1-ru-003"]


def dialog(did: str, lang: str, res: dict[str, CriterionResult]) -> Any:
    return BASE.model_copy(update={"id": did, "lang": lang, "res": res})


def record(dlg: str, cid: str, frm: Any, to: Any, status: str, code: str | None = None) -> Appeal:
    return Appeal.model_validate(
        {
            "id": f"a-{dlg}-{cid}-{to}",
            "kind": "review",
            "dlg": dlg,
            "cid": cid,
            "from": frm,
            "to": to,
            "by": "Р",
            "at": "08.11 11:00",
            "status": status,
            "reason": REASON,
            "reason_code": code,
        }
    )


def test_stats_count_reasons_by_criterion_and_outcome() -> None:
    dialogs = [
        dialog("d1", "RU", {"04": CriterionResult(a=5)}),
        dialog("d2", "RU", {"04": CriterionResult(a=5)}),
    ]
    appeals = [
        record("d1", "04", 5, 10, "changed", "misread"),
        record("d2", "04", 5, 5, "confirmed"),
        record("d2", "01", "yes", "yes", "pending"),
    ]

    stats = appeal_stats(CHECKLIST, dialogs, appeals, REASONS)

    assert stats["decisions"] == 2
    assert stats["reasons"] == [
        {
            "code": "misread",
            "label": "Модель неверно поняла реплику",
            "cid": "04",
            "name": "Корректная и полная консультация",
            "status": "changed",
            "n": 1,
            "share": 0.5,
        },
        {
            "code": None,
            "label": "Без кода",
            "cid": "04",
            "name": "Корректная и полная консультация",
            "status": "confirmed",
            "n": 1,
            "share": 0.5,
        },
    ]


def test_modified_share_counts_decisions_and_manual_answers_per_criterion_and_language() -> None:
    dialogs = [
        dialog("d1", "RU", {"04": CriterionResult(a=5), "01": CriterionResult(a="yes")}),
        dialog("d2", "KZ", {"01": CriterionResult(a="no", model=MANUAL)}),
        # решение вернуло ответ модели: людьми не изменено
        dialog("d3", "RU", {"04": CriterionResult(a=5)}),
    ]
    appeals = [
        record("d1", "04", 5, 10, "changed"),
        record("d3", "04", 5, 10, "changed"),
        record("d3", "04", 10, 5, "changed"),
    ]

    modified = appeal_stats(CHECKLIST, dialogs, appeals, REASONS)["modified"]

    assert (modified["pairs"], modified["changed"], modified["share"]) == (4, 2, 0.5)
    assert modified["criteria"] == [
        {"id": "01", "name": "Установление контакта", "pairs": 2, "changed": 1, "share": 0.5},
        {"id": "04", "name": "Корректная и полная консультация", "pairs": 2, "changed": 1, "share": 0.5},
    ]
    assert modified["langs"] == [
        {"key": "RU", "pairs": 3, "changed": 1, "share": 0.3333},
        {"key": "KZ", "pairs": 1, "changed": 1, "share": 1.0},
    ]


def test_stats_on_empty_state_have_no_shares() -> None:
    stats = appeal_stats(CHECKLIST, [], [], REASONS)

    assert stats == {
        "decisions": 0,
        "reasons": [],
        "modified": {"pairs": 0, "changed": 0, "share": None, "criteria": [], "langs": []},
    }
