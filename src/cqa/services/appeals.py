"""Апелляции и решения проверяющего (review-workflow, решения 13–15). Таблица results не трогается."""

from datetime import datetime

from cqa.adapters.store import Store
from cqa.domain.models import Appeal
from cqa.domain.review import Answer, effective_answer, fingerprint, stamp


def file_appeal(
    store: Store, *, dlg: str, cid: str, ask: Answer, ev: list[int], comment: str, by: str, now: datetime
) -> Appeal:
    checklist = store.current_checklist()
    assert checklist is not None
    criterion = next(c for c in checklist.criteria if c.id == cid)
    fp = fingerprint(checklist, criterion)
    result = store.current_results({cid: fp})[dlg][cid]
    decided = [a for a, afp in store.list_appeals() if a.dlg == dlg and a.cid == cid and afp == fp]
    appeal = Appeal.model_validate(
        {
            "id": "",
            "kind": "appeal",
            "dlg": dlg,
            "cid": cid,
            "from": effective_answer(result, decided),
            "ask": ask,
            "ev": ev,
            "by": by,
            "at": stamp(now),
            "status": "pending",
            "comment": comment,
        }
    )
    return store.add_appeal(appeal, fp)
