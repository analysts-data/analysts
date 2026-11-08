"""Ручной ответ специалиста КК: новый результат пары (диалог, критерий).

Итог считает последний результат, поэтому ручной ответ заменяет ответ модели, а запуск оценки его не трогает:
пара с результатом текущего смысла в план не попадает. Прежние результаты остаются в таблице.
"""

from cqa.adapters.store import Store
from cqa.domain.models import Answer, Criterion, CriterionResult
from cqa.domain.review import MANUAL, allowed_answers, fingerprint
from cqa.services.errors import Conflict, Invalid, NotFound

__all__ = ["MANUAL", "set_answer"]


def _check(c: Criterion, a: Answer) -> None:
    if c.type == "flag":
        keys = {q.k for q in c.questions or []}
        ok = isinstance(a, dict) and set(a) == keys and all(isinstance(v, bool) for v in a.values())
        if not ok:
            raise Invalid(f"Ответ флага {c.id}: да или нет по каждому вопросу ({', '.join(sorted(keys))})")
        return
    allowed = allowed_answers(c)
    if isinstance(a, bool | dict) or a not in allowed:
        raise Invalid(f"Ответ {a} недопустим для критерия {c.id}: допустимы {', '.join(map(str, allowed))}")


def set_answer(store: Store, *, dlg: str, cid: str, a: Answer, reason: str, by: str) -> CriterionResult:
    dialog = store.get_dialog(dlg)
    if dialog is None:
        raise NotFound(f"Диалог {dlg} не найден")
    checklist = store.current_checklist()
    assert checklist is not None, "create_app сеет чек-лист на пустой базе"
    criterion = next((c for c in checklist.criteria if c.id == cid), None)
    if criterion is None:
        raise NotFound(f"Критерия {cid} нет в чек-листе v{checklist.version}")
    if not by.strip():
        raise Invalid("Укажите, кто ставит ответ")
    _check(criterion, a)
    fp = fingerprint(checklist, criterion, dialog.ch)
    for record, rfp in store.list_appeals():
        if record.dlg != dlg or record.cid != cid or rfp != fp:
            continue
        if record.status == "pending":
            raise Conflict(f"По критерию {cid} есть апелляция на рассмотрении: {record.id}")
        if record.status in ("confirmed", "changed"):
            raise Conflict(f"По критерию {cid} уже есть решение {record.id}, ручной ответ его не перекроет")
    result = CriterionResult(a=a, why=reason.strip() or f"Оценено вручную: {by.strip()}", model=MANUAL)
    store.add_result(dlg, cid, checklist.version, fp, result)
    return result
