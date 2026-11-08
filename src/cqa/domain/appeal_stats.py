"""Коды причин решений и доля ответов, изменённых людьми («Modified AutoQA»). Чистые функции.

Пара (диалог, критерий) изменена людьми, если её текущий ответ — ручной или последнее решение
ответ модели заменило. Высокая доля по критерию или языку — прямой сигнал, где модель слаба.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from cqa.domain.models import Appeal, Checklist, Dialog, ReasonCode
from cqa.domain.report import _share
from cqa.domain.review import effective_answer

MANUAL = "вручную"  # CriterionResult.model ручного ответа
NO_CODE = "Без кода"


def _modified(rows: Sequence[tuple[str, bool]]) -> list[dict[str, Any]]:
    out = []
    for key in dict.fromkeys(k for k, _ in rows):
        flags = [m for k, m in rows if k == key]
        out.append(
            {"key": key, "pairs": len(flags), "changed": sum(flags), "share": _share(sum(flags), len(flags))}
        )
    return out


def appeal_stats(
    checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal], reasons: Sequence[ReasonCode]
) -> dict[str, Any]:
    """`dialogs` с текущими `res`, `appeals` — как в GET /api/state."""
    names = {c.id: c.name for c in checklist.criteria}
    labels = {r.code: r.label for r in reasons}
    decided = [a for a in appeals if a.status in ("confirmed", "changed")]
    counts = Counter((a.reason_code, a.cid, a.status) for a in decided)

    pairs: list[tuple[str, str, bool]] = []  # (критерий, язык, изменено людьми)
    for d in dialogs:
        for cid, r in d.res.items():
            mine = [a for a in decided if a.dlg == d.id and a.cid == cid]
            pairs.append((cid, d.lang, r.model == MANUAL or effective_answer(r, mine) != r.a))
    changed = sum(m for _, _, m in pairs)
    criteria = [
        {
            "id": g["key"],
            "name": names.get(g["key"], g["key"]),
            **{k: g[k] for k in ("pairs", "changed", "share")},
        }
        for g in _modified([(cid, m) for cid, _, m in pairs])
    ]

    return {
        "decisions": len(decided),
        "reasons": [
            {
                "code": code,
                "label": labels.get(code, code) if code else NO_CODE,
                "cid": cid,
                "name": names.get(cid, cid),
                "status": status,
                "n": n,
                "share": _share(n, len(decided)),
            }
            for (code, cid, status), n in counts.most_common()
        ],
        "modified": {
            "pairs": len(pairs),
            "changed": changed,
            "share": _share(changed, len(pairs)),
            "criteria": sorted(criteria, key=lambda c: (-c["share"], c["id"])),
            "langs": sorted(_modified([(lang, m) for _, lang, m in pairs]), key=lambda g: -g["pairs"]),
        },
    }
