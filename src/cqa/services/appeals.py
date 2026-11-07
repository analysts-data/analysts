"""Апелляции и решения проверяющего (review-workflow, решения 13–15). Таблица results не трогается."""

from dataclasses import dataclass
from datetime import datetime

from cqa.adapters.store import Store
from cqa.domain.models import Answer as ResultAnswer
from cqa.domain.models import Appeal, Checklist, Criterion, CriterionResult
from cqa.domain.review import Answer, allowed_answers, effective_answer, fingerprint, needs_review, stamp
from cqa.services.errors import Conflict, Invalid, NotFound


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
    if store.get_dialog(dlg) is None:
        raise NotFound(f"Диалог {dlg} не найден")
    checklist, criterion = _criterion(store, cid)
    if criterion.type == "flag":
        raise Invalid(f"Флаг нарушения не оспаривается: у критерия {cid} нет баллов")
    fp = fingerprint(checklist, criterion)
    result = store.current_results({cid: fp}).get(dlg, {}).get(cid)
    if result is None:
        raise Invalid(f"Критерий {cid} ждёт оценки, оспаривать пока нечего")
    records = [(a, afp) for a, afp in store.list_appeals() if a.dlg == dlg and a.cid == cid]
    return _Pair(criterion, fp, result, records)


def _check_allowed(criterion: Criterion, answer: Answer) -> None:
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


def decide(store: Store, appeal_id: str, *, to: Answer, reason: str, reviewer: str, now: datetime) -> Appeal:
    found = store.get_appeal(appeal_id)
    if found is None:
        raise NotFound(f"Апелляция {appeal_id} не найдена")
    appeal = found[0]
    if appeal.status != "pending":
        raise Conflict(f"Апелляция {appeal_id} уже рассмотрена: {appeal.status}")
    _check_signed(reason, reviewer)
    _check_allowed(_criterion(store, appeal.cid)[1], to)
    decided = appeal.model_copy(
        update={
            "to": to,
            "reason": reason.strip(),
            "reviewer": reviewer,
            "decidedAt": stamp(now),
            "status": "confirmed" if to == appeal.from_ else "changed",
        }
    )
    store.save_decision(decided)
    return decided


def record_review(
    store: Store, *, dlg: str, cid: str, frm: Answer, to: Answer, reason: str, reviewer: str, now: datetime
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
            "status": "confirmed" if to == frm else "changed",
            "reviewer": reviewer,
            "reason": reason.strip(),
            "decidedAt": at,
        }
    )
    return store.add_appeal(record, pair.fp)
