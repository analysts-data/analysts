"""Апелляции и решения проверяющего (review-workflow, решения 13–15). Таблица results не трогается.

Коды причин решений (eval-and-delivery, reason-codes): каталог — данные, по умолчанию REASONS."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cqa.adapters.store import Store
from cqa.domain.appeal_stats import appeal_stats
from cqa.domain.models import Answer as ResultAnswer
from cqa.domain.models import Appeal, Checklist, Criterion, CriterionResult, ReasonCode
from cqa.domain.review import Answer, allowed_answers, effective_answer, fingerprint, needs_review, stamp
from cqa.services.errors import Conflict, Invalid, NotFound
from cqa.services.state import current_state

REASONS = [
    ReasonCode.model_validate({"code": code, "label": label, "applies": applies})
    for code, label, applies in (
        ("misread", "Модель неверно поняла реплику", "changed"),
        ("context", "Не учтён контекст диалога", "changed"),
        ("ambiguous", "Критерий сформулирован неоднозначно", "both"),
        ("asr", "Ошибка распознавания речи", "changed"),
        ("violation", "Нарушение подтверждено", "confirmed"),
        ("by_rules", "Оценка верна по регламенту", "confirmed"),
        ("other", "Другое", "both"),
    )
]
OUTCOME = {"confirmed": "оценка оставлена", "changed": "оценка изменена"}
_CODE = re.compile(r"[a-z0-9_-]{1,32}")


def reasons(store: Store) -> list[ReasonCode]:
    return store.appeal_reasons() or REASONS


def save_reasons(store: Store, items: Sequence[ReasonCode]) -> list[ReasonCode]:
    """Заменить каталог целиком. Записи с удалённым кодом остаются как есть, новые решения его не примут."""
    if not items:
        raise Invalid("Нужна хотя бы одна причина")
    seen: set[str] = set()
    for r in items:
        if not _CODE.fullmatch(r.code):
            raise Invalid(f"Код причины «{r.code}»: строчная латиница, цифры, _ и -, до 32 знаков")
        if not r.label.strip():
            raise Invalid(f"У причины {r.code} нет названия")
        if r.code in seen:
            raise Invalid(f"Код причины {r.code} повторяется")
        seen.add(r.code)
    saved = [r.model_copy(update={"label": r.label.strip()}) for r in items]
    store.set_appeal_reasons(saved)
    return saved


def _check_code(store: Store, code: str | None, status: str) -> None:
    if code is None:
        return
    catalogue = reasons(store)
    item = next((r for r in catalogue if r.code == code), None)
    if item is None:
        raise Invalid(f"Неизвестный код причины {code}: допустимы {', '.join(r.code for r in catalogue)}")
    if item.applies not in ("both", status):
        raise Invalid(f"Причина «{item.label}» не подходит к решению «{OUTCOME[status]}»")


def stats(store: Store) -> dict[str, Any]:
    """GET /api/appeals/stats из того же состояния, что GET /api/state."""
    checklist, dialogs, appeals = current_state(store)
    return appeal_stats(checklist, dialogs, appeals, reasons(store))


@dataclass(frozen=True)
class _Pair:
    criterion: Criterion
    fp: str
    result: CriterionResult
    records: list[tuple[Appeal, str]]  # записи пары (диалог, критерий) в порядке подачи

    def current(self) -> ResultAnswer:
        """Ответ с учётом последнего решения; решения прежнего смысла критерия не в счёт (решение 12)."""
        return effective_answer(self.result, [a for a, fp in self.records if fp == self.fp])

    def check_no_pending(self) -> None:
        pending = next((a for a, _ in self.records if a.status == "pending"), None)
        if pending is not None:
            raise Conflict(f"По критерию {self.criterion.id} уже есть {pending.id} на рассмотрении")


def _criterion(store: Store, cid: str) -> tuple[Checklist, Criterion]:
    checklist = store.current_checklist()
    assert checklist is not None, "create_app сеет чек-лист на пустой базе"
    criterion = next((c for c in checklist.criteria if c.id == cid), None)
    if criterion is None:
        raise NotFound(f"Критерия {cid} нет в чек-листе v{checklist.version}")
    return checklist, criterion


def _pair(store: Store, dlg: str, cid: str) -> _Pair:
    dialog = store.get_dialog(dlg)
    if dialog is None:
        raise NotFound(f"Диалог {dlg} не найден")
    checklist, criterion = _criterion(store, cid)
    fp = fingerprint(checklist, criterion, dialog.ch)
    result = store.current_results({cid: fp}).get(dlg, {}).get(cid)
    if result is None:
        raise Invalid(f"Критерий {cid} ждёт оценки, оспаривать пока нечего")
    records = [(a, afp) for a, afp in store.list_appeals() if a.dlg == dlg and a.cid == cid]
    return _Pair(criterion, fp, result, records)


def _check_allowed(criterion: Criterion, answer: Answer) -> None:
    if criterion.type == "flag":
        if not criterion.accepts(answer):
            keys = ", ".join(q.k for q in criterion.questions or [])
            raise Invalid(
                f"Ответ по флагу {criterion.id} — объект с ключами {keys} и значениями true или false"
            )
        return
    allowed = allowed_answers(criterion)
    if answer not in allowed:
        listed = ", ".join(map(str, allowed))
        raise Invalid(f"Ответ {answer} недопустим для критерия {criterion.id}: допустимы {listed}")


def _check_signed(reason: str, reviewer: str) -> None:
    if len(reason.strip()) < 5:
        raise Invalid("Причина решения обязательна: не короче 5 символов")
    if not reviewer.strip():
        raise Invalid("Укажите проверяющего")


def file_appeal(
    store: Store, *, dlg: str, cid: str, ask: Answer, ev: list[int], comment: str, by: str, now: datetime
) -> Appeal:
    pair = _pair(store, dlg, cid)
    pair.check_no_pending()
    _check_allowed(pair.criterion, ask)
    frm = pair.current()
    if ask == frm:
        raise Invalid("Просимый ответ совпадает с текущим")
    if len(comment.strip()) < 10:
        raise Invalid("Комментарий обязателен: не короче 10 символов")
    appeal = Appeal.model_validate(
        {
            "id": "",
            "kind": "appeal",
            "dlg": dlg,
            "cid": cid,
            "from": frm,
            "ask": ask,
            "ev": ev,
            "by": by,
            "at": stamp(now),
            "status": "pending",
            "comment": comment,
        }
    )
    return store.add_appeal(appeal, pair.fp)


def decide(
    store: Store,
    appeal_id: str,
    *,
    to: Answer,
    reason: str,
    reviewer: str,
    now: datetime,
    reason_code: str | None = None,
) -> Appeal:
    found = store.get_appeal(appeal_id)
    if found is None:
        raise NotFound(f"Апелляция {appeal_id} не найдена")
    appeal = found[0]
    if appeal.status != "pending":
        raise Conflict(f"Апелляция {appeal_id} уже рассмотрена: {appeal.status}")
    _check_signed(reason, reviewer)
    _check_allowed(_criterion(store, appeal.cid)[1], to)
    status = "confirmed" if to == appeal.from_ else "changed"
    _check_code(store, reason_code or None, status)
    decided = appeal.model_copy(
        update={
            "to": to,
            "reason": reason.strip(),
            "reviewer": reviewer,
            "decidedAt": stamp(now),
            "status": status,
            "reason_code": reason_code or None,
        }
    )
    store.save_decision(decided)
    return decided


def record_review(
    store: Store,
    *,
    dlg: str,
    cid: str,
    frm: Answer,
    to: Answer,
    reason: str,
    reviewer: str,
    now: datetime,
    reason_code: str | None = None,
) -> Appeal:
    pair = _pair(store, dlg, cid)
    if not needs_review(pair.criterion, pair.result):
        raise Invalid(f"По критерию {cid} модели не расходятся и основание прошло проверку")
    pair.check_no_pending()
    done = next((a for a, fp in pair.records if a.kind == "review" and fp == pair.fp), None)
    if done is not None:
        raise Conflict(f"По критерию {cid} уже есть решение {done.id}")
    current = pair.current()
    if frm != current:
        raise Conflict(f"Текущий ответ по критерию {cid}: {current}. Обновите страницу.")
    _check_allowed(pair.criterion, to)
    _check_signed(reason, reviewer)
    status = "confirmed" if to == frm else "changed"
    _check_code(store, reason_code or None, status)
    at = stamp(now)
    record = Appeal.model_validate(
        {
            "id": "",
            "kind": "review",
            "dlg": dlg,
            "cid": cid,
            "from": frm,
            "to": to,
            "by": reviewer,
            "at": at,
            "status": status,
            "reviewer": reviewer,
            "reason": reason.strip(),
            "decidedAt": at,
            "reason_code": reason_code or None,
        }
    )
    return store.add_appeal(record, pair.fp)
