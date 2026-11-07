"""Билдеры структур контракта для тестов домена (пока без cqa.domain.models).

Строят объекты с полями контракта (design/contract.md); после слияния
bootstrap-harness-core тесты могут перейти на настоящие модели — доступ только
по полям, поведение то же.
"""

from types import SimpleNamespace


def criterion(cid: str, ctype: str = "bool", *, na: bool = False, steps=None, questions=None):
    subs = [SimpleNamespace(k=q["k"]) for q in questions] if questions else None
    return SimpleNamespace(id=cid, type=ctype, na=na, steps=steps, questions=subs)


def checklist(*criteria) -> SimpleNamespace:
    return SimpleNamespace(criteria=list(criteria))


FLAG_KEYS = [{"k": "insult"}, {"k": "paid"}, {"k": "leak"}]


def v3_checklist() -> SimpleNamespace:
    return checklist(
        criterion("01"),
        criterion("02", na=True),
        criterion("03", na=True),
        criterion("04", "scale", na=True, steps=[20, 15, 10, 5, 0]),
        criterion("05"),
        criterion("06", "scale", steps=[10, 7, 4, 0]),
        criterion("07", na=True),
        criterion("08", "flag", questions=FLAG_KEYS),
    )


def result(
    a, *, alt=None, ev=None, evFail=False, model="qwen3-6", calls=1, cost=0.0, tag=None, why=None, quote=None
):
    return SimpleNamespace(
        a=a,
        alt=alt,
        ev=ev or [],
        evFail=evFail,
        model=model,
        calls=calls,
        cost=cost,
        tag=tag,
        why=why,
        quote=quote,
    )


def dialog(dialog_id: str, *, lang: str = "RU", ch: str = "chat") -> SimpleNamespace:
    return SimpleNamespace(id=dialog_id, lang=lang, ch=ch)
