"""Настройка чек-листа без модели: шкала оценок, «что если» и нормировка весов. Чистые функции.

Итог везде — `scoring.total` по ответам с учётом решений (`review.effective_answers`): те же числа,
что видят интерфейс и отчёт. Каждое изменение итога объясняется словами: какой критерий и почему.
"""

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel

from cqa.domain.checklist_export import CHANNEL, FIELD, diff, shares_of
from cqa.domain.models import Answer, Checklist, Criterion, Dialog
from cqa.domain.scoring import frac, r2, total

# --- шкала оценок ---


class Band(BaseModel):
    min: float  # нижняя граница итога, включительно
    label: str
    tone: Literal["ok", "warn", "risk"] | None = None


class Bands(BaseModel):
    bands: list[Band]  # от лучшей к худшей, последняя граница 0
    why: str  # обоснование границ для руководства


def _n(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def band_errors(b: Bands) -> dict[str, str]:
    """Путь поля → ошибка по-русски. Границы нижние, строго по убыванию, в 0–100, последняя 0:
    у любого итога ровно одна оценка."""
    errors: dict[str, str] = {}
    if not b.why.strip():
        errors["why"] = "Обоснование шкалы не заполнено: напишите, почему выбраны эти границы"
    if not b.bands:
        return errors | {"bands": "Нужна хотя бы одна оценка с границей 0"}
    seen: dict[str, int] = {}
    for i, x in enumerate(b.bands):
        p, k = f"bands.{i}", i + 1
        if not 0 <= x.min <= 100:
            errors[f"{p}.min"] = f"Оценка {k}: граница {_n(x.min)} вне диапазона 0–100"
        elif i and x.min >= (prev := b.bands[i - 1].min):
            errors[f"{p}.min"] = (
                f"Оценка {k}: граница {_n(x.min)} должна быть меньше границы оценки {i} ({_n(prev)}) — "
                "оценки идут от лучшей к худшей и не пересекаются"
            )
        label = x.label.strip()
        if not label:
            errors[f"{p}.label"] = f"Оценка {k}: пустое название"
        elif label in seen:
            errors[f"{p}.label"] = f"Оценка {k}: название «{label}» уже есть у оценки {seen[label]}"
        seen.setdefault(label, k)
    last = b.bands[-1]
    if last.min != 0 and f"bands.{len(b.bands) - 1}.min" not in errors:
        errors[f"bands.{len(b.bands) - 1}.min"] = (
            f"Оценка {len(b.bands)}: последняя граница должна быть 0, "
            f"иначе итог ниже {_n(last.min)} останется без оценки"
        )
    return errors


def band_of(bands: Sequence[Band], t: float | None) -> Band | None:
    """Первая оценка, чью границу итог достигает (границы по убыванию); нет итога — нет оценки."""
    return None if t is None else next((b for b in bands if t >= b.min), None)


# --- «что если» ---


def _t(x: float | None) -> str:
    return "нет итога" if x is None else f"{x:.2f}".replace(".", ",")


def _answer(c: Criterion, a: Answer) -> str:
    if isinstance(a, int):
        return f"{a} из {max(c.steps or [a])}"
    return {"yes": "Да", "no": "Нет", "na": "N/A"}.get(a, "флаг") if isinstance(a, str) else "флаг"


def _word(k: int, one: str, few: str, many: str) -> str:
    if k % 10 == 1 and k % 100 != 11:
        return one
    return few if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14 else many


def _dialogs(k: int) -> str:
    return f"{k} {_word(k, 'диалог', 'диалога', 'диалогов')}"


def _reasons(
    old: Checklist, new: Checklist, a0: Mapping[str, Answer], a1: Mapping[str, Answer], fields: dict[str, str]
) -> list[str]:
    """Почему меняется итог диалога: только критерии, входящие в его итог до или после."""
    if old.rules != new.rules:
        return ["изменены общие правила: все критерии ждут новой оценки"]
    before = {c.id: c for c in old.criteria}
    out = []
    for c in new.criteria:
        p, x, y = before.get(c.id), a0.get(c.id), a1.get(c.id)
        f0 = frac(p, x) if p is not None and x is not None else None
        f1 = frac(c, y) if y is not None else None
        if f0 is None and f1 is None:
            continue  # N/A, флаг или нет ответа и до, и после: в итог не входит
        if y is None:
            why = f" (изменено: {fields[c.id]})" if c.id in fields else ""
            out.append(f"«{c.name}» ждёт новой оценки{why}, до неё не входит в итог")
        elif p is None or x is None:
            out.append(f"«{c.name}»: найден прежний ответ «{_answer(c, y)}» для этого смысла критерия")
        elif x != y or f0 != f1:
            out.append(f"«{c.name}»: ответ «{_answer(p, x)}» → «{_answer(c, y)}»")
        if p is not None and f0 is not None and f1 is not None and p.w != c.w:
            out.append(f"вес «{c.name}» {_n(p.w)} → {_n(c.w)}")
    kept = {c.id for c in new.criteria}
    for p in old.criteria:
        x = a0.get(p.id)
        if p.id not in kept and x is not None and frac(p, x) is not None:
            out.append(f"«{p.name}» удалён: ответ «{_answer(p, x)}» больше не входит в итог")
    return out


def _avg(ts: Sequence[float | None]) -> float | None:
    xs = [t for t in ts if t is not None]
    return r2(sum(xs) / len(xs)) if xs else None


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else r2(b - a)


def _signed(x: float) -> str:
    return ("+" if x > 0 else "−" if x < 0 else "±") + _t(abs(x))


def simulate(
    old: Checklist,
    new: Checklist,
    dialogs: Sequence[Dialog],
    before: Mapping[str, Mapping[str, Answer]],
    after: Mapping[str, Mapping[str, Answer]],
    bands: Sequence[Band],
) -> dict[str, Any]:
    """Итоги, если сохранить `new` вместо `old`. `before`/`after` — ответы диалогов с учётом решений
    по смыслу критериев старой и новой версии (`after` без ответа — критерий ждёт оценки)."""
    d = diff(old, new)
    fields = {
        ch["id"]: ", ".join(FIELD.get(f["field"], f["field"]) for f in ch["fields"])
        for ch in d["changed"]
        if ch["reevaluate"]
    }
    known = {c.id for c in old.criteria}
    meaning = {c.id for c in new.criteria if d["rules_changed"] or c.id in fields or c.id not in known}
    rows: list[dict[str, Any]] = []
    for dlg in dialogs:
        a0, a1 = before.get(dlg.id, {}), after.get(dlg.id, {})
        t0, t1 = total(old, a0), total(new, a1)
        b0, b1 = band_of(bands, t0), band_of(bands, t1)
        why = _reasons(old, new, a0, a1, fields)
        text = (
            f"Итог: {_t(t0)} → {_t(t1)}, потому что {'; '.join(why)}"
            if t0 != t1
            else f"Итог не меняется: {_t(t0)}" + (f" ({'; '.join(why)})" if why else "")
        )
        rows.append(
            {
                "id": dlg.id, "title": dlg.title, "ch": dlg.ch, "lang": dlg.lang,
                "before": t0, "after": t1, "delta": _delta(t0, t1),
                "band_before": b0.label if b0 else None, "band_after": b1.label if b1 else None,
                "why": why, "text": text,
                "answers": [
                    {"id": c.id, "name": c.name, "before": a0.get(c.id), "after": a1.get(c.id)}
                    for c in new.criteria
                    if c.id in meaning or a0.get(c.id) != a1.get(c.id)
                ],
            }
        )  # fmt: skip

    def group(key: str, label: Mapping[str, str]) -> list[dict[str, Any]]:
        out = []
        for k in dict.fromkeys(r[key] for r in rows):
            rs = [r for r in rows if r[key] == k]
            a, b = _avg([r["before"] for r in rs]), _avg([r["after"] for r in rs])
            out.append({"key": k, "label": label.get(k, k), "n": len(rs), "avg_before": a, "avg_after": b,
                        "delta": _delta(a, b)})  # fmt: skip
        return sorted(out, key=lambda g: -g["n"])

    moves: dict[tuple[str | None, str | None], int] = {}
    for r in rows:
        if r["before"] is not None and r["band_before"] != r["band_after"]:
            key = (r["band_before"], r["band_after"])
            moves[key] = moves.get(key, 0) + 1

    def move_text(frm: str | None, to: str | None, k: int) -> str:
        verb = _word(k, "перейдёт", "перейдут", "перейдут")
        target = f"в „{to}“" if to else "в «без итога» до новой оценки"
        return f"{_dialogs(k)} {verb} из „{frm}“ {target}"

    move_list = [
        {"from": f, "to": t, "n": k, "text": move_text(f, t, k)}
        for (f, t), k in sorted(moves.items(), key=lambda kv: -kv[1])
    ]

    s0, s1 = shares_of(old), shares_of(new)
    before_w = {c.id: c for c in old.criteria}
    weights = [
        {"id": c.id, "name": c.name, "from": prev.w, "to": c.w,
         "share_from": round(s0.get(c.id, 0.0), 2), "share_to": round(s1.get(c.id, 0.0), 2)}
        for c in new.criteria
        if (prev := before_w.get(c.id)) is not None and prev.w != c.w
    ]  # fmt: skip

    def pending_why(cid: str) -> str:
        if d["rules_changed"]:
            return "изменены общие правила"
        return f"изменено: {fields[cid]}" if cid in fields else "новый критерий"

    pending = [
        {
            "id": c.id,
            "name": c.name,
            "why": pending_why(c.id),
            "dialogs": sum(c.id not in after.get(dlg.id, {}) for dlg in dialogs),
        }
        for c in new.criteria
        if d["rules_changed"] or c.id in fields or c.id not in before_w
    ]

    t0s, t1s = [r["before"] for r in rows], [r["after"] for r in rows]
    summary = {
        "dialogs": len(rows),
        "scored_before": sum(t is not None for t in t0s),
        "scored_after": sum(t is not None for t in t1s),
        "avg_before": _avg(t0s),
        "avg_after": _avg(t1s),
        "delta": _delta(_avg(t0s), _avg(t1s)),
        "changed": sum(r["before"] != r["after"] for r in rows),
        "up": sum((r["delta"] or 0) > 0 for r in rows),
        "down": sum((r["delta"] or 0) < 0 for r in rows),
        "lost_total": sum(r["before"] is not None and r["after"] is None for r in rows),
    }
    distribution = [
        {"label": b.label, "tone": b.tone, "min": b.min,
         "before": sum(r["band_before"] == b.label for r in rows),
         "after": sum(r["band_after"] == b.label for r in rows)}
        for b in bands
    ]  # fmt: skip
    return {
        "summary": summary,
        "groups": {
            "ch": group("ch", {k: v.capitalize() for k, v in CHANNEL.items()}),
            "lang": group("lang", {}),
        },
        "bands": distribution,
        "moves": move_list,
        "weights": weights,
        "pending": pending,
        "removed": d["removed"],
        "dialogs": rows,
        "findings": _findings(summary, move_list, pending, d["removed"]),
    }


def _findings(
    s: dict[str, Any],
    moves: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    removed: list[dict[str, Any]],
) -> list[str]:
    if not s["scored_before"] and not s["scored_after"]:
        return ["Оценённых диалогов нет: сравнивать нечего. Запустите оценку, затем повторите «Что если»."]
    out = []
    if s["delta"] is not None:
        counts = (
            f"по {s['scored_before']} оценённым диалогам"
            if s["scored_before"] == s["scored_after"]
            else f"по {s['scored_before']} и {s['scored_after']} оценённым диалогам"
        )
        out.append(
            f"Средний итог: {_t(s['avg_before'])} → {_t(s['avg_after'])} ({_signed(s['delta'])}) {counts}."
        )
    out.append(
        f"Итог изменится у {s['changed']} из {s['dialogs']}: вырастет у {s['up']}, снизится у {s['down']}."
        if s["changed"]
        else "Итоги диалогов не изменятся."
    )
    out += [m["text"] + "." for m in moves]
    if pending:
        names = ", ".join(f"«{p['name']}»" for p in pending)
        out.append(
            f"Ждут новой оценки после сохранения: {names}. До неё итог считается без них — "
            "запустите оценку, чтобы итог стал полным."
        )
    if s["lost_total"]:
        out.append(
            f"У {_dialogs(s['lost_total'])} не останется оценённых критериев: итога не будет до оценки."
        )
    if removed:
        out.append(
            "Удалены: " + ", ".join(f"«{r['name']}»" for r in removed) + " — их ответы не входят в итог."
        )
    return out


# --- нормировка весов ---


def normalize(cl: Checklist) -> dict[str, Any]:
    """Веса оценочных критериев → целые с суммой ровно 100 (метод наибольших остатков).

    Каждый вес × 100 / Σ, округление вниз; остаток по одному — критериям с наибольшей дробной частью,
    при равенстве — с большим исходным весом, затем по порядку в чек-листе. Дроби точные (`Fraction`).
    Флаги баллов не дают, их вес не меняется. Сумма 0 — поровну.
    """
    scored = [c for c in cl.criteria if c.type != "flag"]
    if not scored:
        return {"checklist": cl, "changes": [], "shares": {},
                "explanation": "Оценочных критериев нет: нормировать нечего."}  # fmt: skip
    s = sum(Fraction(c.w) for c in scored)
    exact = {c.id: 100 * Fraction(c.w) / s if s else Fraction(100, len(scored)) for c in scored}
    new = {cid: int(x) for cid, x in exact.items()}
    rest = 100 - sum(new.values())
    order = sorted(enumerate(scored), key=lambda ic: (-(exact[ic[1].id] - new[ic[1].id]), -ic[1].w, ic[0]))
    bumped = [c for _, c in order[:rest]]
    for c in bumped:
        new[c.id] += 1
    out = cl.model_copy(
        update={
            "criteria": [c.model_copy(update={"w": new[c.id]}) if c.id in new else c for c in cl.criteria]
        }
    )
    changes = [
        {"id": c.id, "name": c.name, "from": c.w, "to": new[c.id], "exact": round(float(exact[c.id]), 2)}
        for c in scored
        if c.w != new[c.id]
    ]
    if not changes:
        explanation = "Сумма весов уже 100, веса целые: ничего не изменилось."
    else:
        how = (
            f"Сумма весов 0: итог не посчитать, поэтому 100 разделено поровну между {len(scored)} критериями."
            if not s
            else f"Сумма весов была {_n(float(s))}. Каждый вес умножен на 100 / {_n(float(s))} "
            "и округлён до целого вниз."
        )
        bonus = (
            f" Остаток округления {rest} отдан по одному критериям с наибольшей дробной частью: "
            + ", ".join(f"«{c.name}»" for c in bumped)
            + "."
            if rest
            else ""
        )
        explanation = (
            how + bonus + " Итог зависит только от отношения весов, поэтому итоги диалогов меняются лишь "
            "на сдвиг от округления; точную разницу покажет «Что если»."
        )
    if any(c.type == "flag" for c in cl.criteria):
        explanation += " Флаги баллов не дают, их вес не меняется."
    return {
        "checklist": out,
        "changes": changes,
        "shares": {k: round(v, 2) for k, v in shares_of(out).items()},
        "explanation": explanation,
    }
