"""Рекомендации оператору, проверяющему, руководителю и автору чек-листа (design/contract.md «Рекомендации»).

Чистые функции без модели: явные правила над ответами с учётом решений (`effective_answer`) и формулой
итога (`scoring.total`), без весовых сумм. Каждый пункт несёт `why` — «почему» одним предложением — и
`basis`: правило словами, числа с размерами выборок, диалоги с номерами реплик. Если правило сработало бы,
но выборка меньше порога, пункт уходит в `insufficient`: «недостаточно данных (n=3, нужно ≥5)».
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any

from cqa.domain.models import MANUAL, Answer, Appeal, Checklist, Criterion, Dialog, Line
from cqa.domain.products import topic_name
from cqa.domain.report import CHANNEL, NOBODY, _d, _dialogs, _pct
from cqa.domain.review import effective_answer
from cqa.domain.scoring import frac, r2, total

# Пороги — именованные параметры; ответ отдаёт их вместе с обоснованием (`params`).
MIN_N = 5
MIN_UNIFORM = 20
UNIFORM_SHARE = 0.95
DISPUTE_SHARE = 0.2
NA_SHARE = 0.5
WEIGHT_RATIO = 2
ATTENTION_GAP = 10
TREND_DROP = 5
LOW_SD = 1
REPEAT = 2
SKILLS, EXAMPLES, BASIS = 3, 2, 5  # навыков оператору; примеров у навыка; диалогов в basis сводного пункта

PARAMS: dict[str, tuple[float, str]] = {
    "MIN_N": (
        MIN_N,
        "При n < 5 один диалог сдвигает долю на 20 п. п. и больше: вывод держится на случайности",
    ),
    "MIN_UNIFORM": (MIN_UNIFORM, "95 % одинаковых ответов различимы только от 20 ответов (19 из 20)"),
    "UNIFORM_SHARE": (
        UNIFORM_SHARE,
        "Отличается не больше одного ответа из 20: критерий почти ничего не различает",
    ),
    "DISPUTE_SHARE": (
        DISPUTE_SHARE,
        "Спорна каждая пятая оценка: изменена решением, вручную или вторым мнением",
    ),
    "NA_SHARE": (NA_SHARE, "Критерий чаще неприменим, чем применим"),
    "WEIGHT_RATIO": (WEIGHT_RATIO, "Доля потерь баллов вдвое больше доли веса критерия в сумме весов"),
    "ATTENTION_GAP": (
        ATTENTION_GAP,
        "10 баллов из 100 — полностью потерянный критерий веса 10 в каждом диалоге",
    ),
    "TREND_DROP": (
        TREND_DROP,
        "5 баллов из 100 — половина критерия веса 10; меньшие колебания не выделяются",
    ),
    "LOW_SD": (
        LOW_SD,
        "Итог ниже среднего набора больше чем на одно стандартное отклонение — заметно хуже обычного",
    ),
    "REPEAT": (REPEAT, "Причина повторилась хотя бы в двух диалогах — уже не единичный случай"),
}


def _params(*names: str) -> list[dict[str, Any]]:
    return [{"name": n, "value": PARAMS[n][0], "why": PARAMS[n][1]} for n in names]


def _short(subject: str, n: int, need: int) -> dict[str, Any]:
    return {"subject": subject, "n": n, "need": need, "text": f"недостаточно данных (n={n}, нужно ≥{need})"}


def _item(
    title: str, why: str, rule: str, numbers: dict[str, Any], dialogs: list[dict[str, Any]], /, **extra: Any
) -> dict[str, Any]:
    return {
        **extra,
        "title": title,
        "why": why,
        "basis": {"rule": rule, "numbers": numbers, "dialogs": dialogs},
    }


@dataclass(frozen=True)
class _Row:
    d: Dialog
    ans: dict[str, Answer]  # с учётом последнего решения
    total: float | None


def _rows(checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]) -> list[_Row]:
    pairs: dict[tuple[str, str], list[Appeal]] = {}
    for a in appeals:
        pairs.setdefault((a.dlg, a.cid), []).append(a)
    out = []
    for d in dialogs:
        ans = {cid: effective_answer(r, pairs.get((d.id, cid), [])) for cid, r in d.res.items()}
        out.append(_Row(d, ans, total(checklist, ans)))
    return out


def _op(d: Dialog) -> str | None:
    return d.operator


def _product(d: Dialog) -> str | None:
    return topic_name(d)


def _scored(checklist: Checklist) -> list[Criterion]:
    return [c for c in checklist.criteria if c.type != "flag"]


def _f(c: Criterion, r: _Row) -> float | None:
    a = r.ans.get(c.id)
    return None if a is None else frac(c, a)


def _top(c: Criterion) -> Answer:
    return "yes" if c.type == "bool" else max(c.steps or [0])


def _say(a: Answer) -> str:
    return {"yes": "да", "no": "нет", "na": "N/A"}.get(a, a) if isinstance(a, str) else str(a)


def _ev(r: _Row, c: Criterion) -> list[int]:
    res = r.d.res.get(c.id)
    return list(res.ev) if res else []


def _lost_lines(checklist: Checklist, r: _Row) -> list[int]:
    return sorted({n for c in _scored(checklist) if (f := _f(c, r)) is not None and f < 1 for n in _ev(r, c)})


def _flags(checklist: Checklist, r: _Row) -> list[tuple[Criterion, list[str]]]:
    out = []
    for c in checklist.criteria:
        a = r.ans.get(c.id)
        if (
            c.type == "flag"
            and isinstance(a, dict)
            and (hit := [q.label for q in c.questions or [] if a.get(q.k)])
        ):
            out.append((c, hit))
    return out


# --- Оператору: коучинг ---

SKILL_RULE = (
    f"До {SKILLS} критериев с наибольшим отставанием средней доли баллов сотрудника от доли коллег "
    f"(других сотрудников); учитываются критерии с отставанием и не меньше {MIN_N} применимыми оценками "
    "у обеих сторон. Доля: да 1, нет 0, шкала — ступень / максимум, N/A не входит; ответы — с учётом решений."
)


def for_operator(
    checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal], name: str
) -> dict[str, Any] | None:
    """Три навыка для роста, примеры из своих диалогов, «как сказать лучше», образцы коллег.

    None — у сотрудника нет диалогов."""
    rows = _rows(checklist, dialogs, appeals)
    mine = [r for r in rows if _op(r.d) == name]
    if not mine:
        return None
    team = [r for r in rows if _op(r.d) not in (None, name)]
    stats, insufficient = [], []
    for i, c in enumerate(_scored(checklist)):
        fs = [f for r in mine if (f := _f(c, r)) is not None]
        ts = [f for r in team if (f := _f(c, r)) is not None]
        if not fs or not ts:
            continue
        s, t = mean(fs), mean(ts)
        if min(len(fs), len(ts)) < MIN_N:
            if s < t:
                insufficient.append(_short(f"«{c.name}»", min(len(fs), len(ts)), MIN_N))
            continue
        stats.append((i, c, s, t, len(fs), len(ts)))

    items = []
    weak = sorted((x for x in stats if x[2] < x[3]), key=lambda x: (x[2] - x[3], x[0]))
    for _, c, s, t, n, tn in weak[:SKILLS]:
        lost = sorted(
            ((f, r) for r in mine if (f := _f(c, r)) is not None and f < 1), key=lambda x: (x[0], x[1].d.id)
        )
        refs = []
        for _, r in lost[:EXAMPLES]:
            res = r.d.res[c.id]
            refs.append(
                {
                    "id": r.d.id,
                    "cid": c.id,
                    "lines": list(res.ev),
                    "seg": res.seg,
                    "quote": res.quote,
                    "tag": res.tag,
                    "a": r.ans[c.id],
                }
            )
        better: list[dict[str, str]] = []
        for _, r in lost:
            text = r.d.res[c.id].better
            if text and text not in [b["text"] for b in better] and len(better) < EXAMPLES:
                better.append({"id": r.d.id, "text": text})
        items.append(
            _item(
                f"Подтянуть «{c.name}»",
                f"Средняя доля баллов по критерию «{c.name}» — {_d(s)}, у коллег — {_d(t)} ({n} ваших оценок "
                f"и {tn} у коллег); баллы потеряны в {len(lost)} из {n}.",
                SKILL_RULE,
                {
                    "share": round(s, 4),
                    "team_share": round(t, 4),
                    "gap": round(s - t, 4),
                    "n": n,
                    "team_n": tn,
                    "lost": len(lost),
                },
                refs,
                kind="skill",
                cid=c.id,
                name=c.name,
                better=better,
                peers=_peers(c, lost, team),
            )
        )

    strength = None
    if best := max(
        (x for x in stats if x[2] >= x[3]), key=lambda x: (x[2], x[2] - x[3], -x[0]), default=None
    ):
        _, c, s, t, n, tn = best
        full = sorted((r for r in mine if _f(c, r) == 1), key=lambda r: r.d.id)[:EXAMPLES]
        strength = _item(
            f"Сильная сторона: «{c.name}»",
            f"Лучший ваш результат: доля баллов {_d(s)} при {_d(t)} у коллег "
            f"({n} ваших оценок и {tn} у коллег).",
            "Критерий с наибольшей своей долей баллов среди тех, где она не ниже доли коллег, "
            f"при ≥ {MIN_N} оценках у обеих сторон.",
            {"share": round(s, 4), "team_share": round(t, 4), "n": n, "team_n": tn},
            [{"id": r.d.id, "cid": c.id, "lines": _ev(r, c)} for r in full],
            cid=c.id,
            name=c.name,
        )

    totals = [r.total for r in mine if r.total is not None]
    team_totals = [r.total for r in team if r.total is not None]
    return {
        "for": "operator",
        "operator": name,
        "params": _params("MIN_N"),
        "summary": {
            "dialogs": len(mine),
            "scored": len(totals),
            "avg_total": r2(mean(totals)) if totals else None,
            "team_dialogs": len(team_totals),
            "team_avg_total": r2(mean(team_totals)) if team_totals else None,
        },
        "items": items,
        "strength": strength,
        "insufficient": insufficient,
    }


def _peers(c: Criterion, lost: list[tuple[float, _Row]], team: list[_Row]) -> list[dict[str, Any]]:
    """Диалоги коллег с максимумом по критерию: сначала тот же продукт и язык, затем продукт, затем язык."""
    products = {p for _, r in lost if (p := _product(r.d))}
    langs = {r.d.lang for _, r in lost}
    found = []
    for r in team:
        match = [m for m, ok in (("продукт", _product(r.d) in products), ("язык", r.d.lang in langs)) if ok]
        if match and _f(c, r) == 1:
            found.append((match, r))
    found.sort(key=lambda x: ("продукт" not in x[0], "язык" not in x[0], x[1].d.id))
    return [
        {"id": r.d.id, "operator": _op(r.d), "lines": _ev(r, c), "quote": r.d.res[c.id].quote, "match": m}
        for m, r in found[:EXAMPLES]
    ]


# --- Проверяющему: очередь «Проверить сначала» ---

QA_RULES = [
    ("gross", "Грубое нарушение в непроверенном диалоге"),
    ("disagree", "Второе мнение разошлось с основной моделью, решения нет"),
    ("evidence", "Цитата-основание не найдена в реплике, решения нет"),
    ("jev", "Jev не уверен в ответе, решения нет"),
    ("low", f"Итог ниже среднего набора больше чем на {LOW_SD} стандартное отклонение"),
    ("tone", "Клиент повысил тон по разбору звука записи"),
    ("new_operator", f"Новый сотрудник: меньше {MIN_N} диалогов в наборе"),
    ("product_trend", "Продукт со снижением итога, диалог из поздней половины периода"),
]
QA_ORDER = (
    "Диалог встаёт по первому сработавшему правилу списка (1 — важнее всех); при равенстве — больше "
    "сработавших правил, затем ниже итог (без итога — первым), затем id. Проверенные диалоги и пары "
    "с решением не входят."
)


@dataclass(frozen=True)
class _Set:
    """Данные набора, нужные правилам очереди."""

    decided: set[tuple[str, str]]
    low: tuple[float, float, float] | None  # порог, среднее, σ; None — мало итогов
    counts: Counter[str]  # диалогов у сотрудника
    late: dict[str, dict[str, Any]]  # id диалога поздней половины → тренд его продукта
    prosody: Mapping[str, Mapping[str, Any]]


def _reasons(checklist: Checklist, r: _Row, s: _Set) -> list[dict[str, Any]]:
    """Сработавшие правила диалога в порядке QA_RULES."""
    out: list[dict[str, Any]] = []

    def add(k: str, text: str, lines: Sequence[int], cid: str | None = None) -> None:
        out.append({"k": k, "text": text, "cid": cid, "lines": list(lines)})

    for c, labels in _flags(checklist, r):
        add("gross", f"Грубое нарушение: {', '.join(labels)}", _ev(r, c), c.id)
    for k in ("disagree", "evidence", "jev"):
        for c in _scored(checklist):
            res = r.d.res.get(c.id)
            if res is None or (r.d.id, c.id) in s.decided:
                continue
            jev = (res.model or "").startswith("jev")
            if k == "disagree" and res.alt is not None and res.alt != res.a:
                add(k, f"«{c.name}»: модель — {_say(res.a)}, второе мнение — {_say(res.alt)}", res.ev, c.id)
            elif k == "evidence" and res.evFail and not jev:
                add(k, f"«{c.name}»: цитата-основание не найдена в реплике", res.ev, c.id)
            elif k == "jev" and res.evFail and jev:
                add(k, f"«{c.name}»: {res.why or 'Jev не уверен в ответе'}", res.ev, c.id)
    if s.low and r.total is not None and r.total < s.low[0]:
        cut, m, sd = s.low
        text = f"Итог {_d(r.total)} ниже порога {_d(cut)} (среднее {_d(m)} − {LOW_SD} × σ {_d(sd)})"
        add("low", text, _lost_lines(checklist, r))
    if r.d.ch == "call" and (p := s.prosody.get(r.d.id)):
        client = {ln.n for ln in r.d.lines or [] if isinstance(ln, Line) and ln.who == "client"}
        hit = [
            x["n"] for x in p.get("lines") or [] if "raised" in (x.get("flags") or []) and x["n"] in client
        ]
        if hit:
            add("tone", f"Клиент повысил тон в репликах {', '.join(map(str, hit))}", hit)
    if (op := _op(r.d)) and s.counts[op] < MIN_N:
        add("new_operator", f"Новый сотрудник {op}: {_dialogs(s.counts[op])} в наборе, меньше {MIN_N}", [])
    if t := s.late.get(r.d.id):
        n = t["basis"]["numbers"]
        text = f"Продукт «{t['label']}»: средний итог упал с {_d(n['earlier_avg'])} до {_d(n['later_avg'])}"
        add("product_trend", text, _lost_lines(checklist, r))
    return out


def for_qa(
    checklist: Checklist,
    dialogs: Sequence[Dialog],
    appeals: Sequence[Appeal],
    prosody: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """`prosody` — сохранённые разборы звука звонков (id → тело GET /api/dialogs/{id}/prosody)."""
    rows = _rows(checklist, dialogs, appeals)
    totals = [r.total for r in rows if r.total is not None]
    insufficient = []
    low = None
    if len(totals) >= MIN_N:
        m, sd = mean(totals), pstdev(totals)
        low = (m - LOW_SD * sd, m, sd)
    elif totals:
        insufficient.append(_short("низкий итог", len(totals), MIN_N))
    trends, _ = _trends(checklist, rows, ("product",))
    s = _Set(
        decided={(a.dlg, a.cid) for a in appeals if a.status in ("confirmed", "changed")},
        low=low,
        counts=Counter(op for r in rows if (op := _op(r.d))),
        late={d["id"]: t for t in trends for d in t["late"]},
        prosody=prosody,
    )
    rank = {k: i for i, (k, _) in enumerate(QA_RULES)}

    items = []
    for r in rows:
        reasons = [] if r.d.reviewed else _reasons(checklist, r, s)
        if not reasons:
            continue
        first = rank[reasons[0]["k"]]
        also = "; ".join(x["text"] for x in reasons[1:])
        items.append(
            (
                (first, -len(reasons), -1 if r.total is None else r.total, r.d.id),
                _item(
                    QA_RULES[first][1],
                    f"Правило {first + 1} из {len(QA_RULES)}: {reasons[0]['text']}"
                    + (f"; также: {also}." if also else "."),
                    QA_ORDER,
                    {"rule": first + 1, "rules_matched": len(reasons), "total": r.total},
                    [{"id": r.d.id, "lines": sorted({n for x in reasons for n in x["lines"]})}],
                    id=r.d.id,
                    rule=reasons[0]["k"],
                    total=r.total,
                    operator=_op(r.d),
                    reasons=reasons,
                ),
            )
        )
    return {
        "for": "qa",
        "params": _params("MIN_N", "LOW_SD", "TREND_DROP"),
        "rules": [{"k": k, "n": i + 1, "text": text} for i, (k, text) in enumerate(QA_RULES)],
        "items": [it for _, it in sorted(items, key=lambda x: x[0])],
        "insufficient": insufficient,
    }


# --- Тренды: группы, где итог снижается ---

DIMS = {"product": "продукт", "ch": "канал", "lang": "язык"}
TREND_RULE = (
    "Оценённые диалоги группы по времени (`at`) делятся пополам; снижение — средний итог поздней "
    f"половины ниже ранней на {TREND_DROP} баллов и больше при ≥ {MIN_N} диалогах в каждой половине."
)


def _when(d: Dialog) -> str:
    # ponytail: года в `at` нет, на стыке декабря и января порядок ломается
    return d.at[3:5] + d.at[:2] + d.at[6:]


def _trends(
    checklist: Checklist, rows: Sequence[_Row], dims: Sequence[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items, insufficient = [], []
    scored = sorted((r for r in rows if r.total is not None), key=lambda r: (_when(r.d), r.d.id))
    for di, dim in enumerate(dims):
        groups: dict[str, list[_Row]] = {}
        for r in scored:
            key = _product(r.d) if dim == "product" else r.d.ch if dim == "ch" else r.d.lang
            if key:
                groups.setdefault(key, []).append(r)
        for key in sorted(groups):
            g = groups[key]
            early, later = g[: len(g) // 2], g[len(g) // 2 :]
            if not early:
                continue
            e, lt = mean(r.total or 0 for r in early), mean(r.total or 0 for r in later)
            if e - lt < TREND_DROP:
                continue
            label = CHANNEL.get(key, key) if dim == "ch" else key
            if len(early) < MIN_N:
                insufficient.append(_short(f"{DIMS[dim]} {label}", len(early), MIN_N))
                continue
            worst = sorted(later, key=lambda r: (r.total or 0, r.d.id))
            items.append(
                (
                    (-(e - lt), di, key),
                    _item(
                        f"{DIMS[dim].capitalize()} «{label}»: средний итог снизился на {_d(e - lt)}",
                        f"Средний итог ранних {len(early)} диалогов — {_d(e)}, "
                        f"поздних {len(later)} — {_d(lt)}.",
                        TREND_RULE,
                        {
                            "earlier_n": len(early),
                            "later_n": len(later),
                            "earlier_avg": r2(e),
                            "later_avg": r2(lt),
                            "drop": r2(e - lt),
                        },
                        [{"id": r.d.id, "lines": _lost_lines(checklist, r)} for r in worst[:BASIS]],
                        dim=dim,
                        key=key,
                        label=label,
                        late=[{"id": r.d.id} for r in later],
                    ),
                )
            )
    return [it for _, it in sorted(items, key=lambda x: x[0])], insufficient


# --- Руководителю: процессы, сотрудники, тренды ---

VERB = {
    "Инструкция": "Обновить инструкцию",
    "Сервис": "Изменить процесс сервиса",
    "Продукт": "Доработать продукт",
    NOBODY: "Назначить ответственного",
}
ACTION_RULE = (
    "Сниженные ответы (доля < 1) с одной причиной `tag` в диалогах одного продукта, причина — "
    f"хотя бы в {REPEAT} диалогах. Рост = Σ(итог диалога, если эти критерии на максимуме − текущий итог) / "
    "число оценённых диалогов, итог — по формуле «Итог». Порядок — по росту."
)
ATTENTION_RULE = (
    "Сотрудник в списке, если в его диалогах есть грубое нарушение (при любом n) или его средний итог ниже "
    f"среднего по набору на {ATTENTION_GAP} баллов и больше при ≥ {MIN_N} оценённых диалогах."
)


def for_manager(
    checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal], owners: Mapping[str, str]
) -> dict[str, Any]:
    rows = [r for r in _rows(checklist, dialogs, appeals) if r.total is not None]
    n_all = len(rows)
    avg = mean(r.total or 0 for r in rows) if rows else 0.0
    insufficient: list[dict[str, Any]] = []

    groups: dict[tuple[str, str], list[tuple[_Row, list[Criterion]]]] = {}
    for r in rows:
        by_tag: dict[str, list[Criterion]] = {}
        for c in _scored(checklist):
            res, f = r.d.res.get(c.id), _f(c, r)
            if res and res.tag and f is not None and f < 1:
                by_tag.setdefault(res.tag, []).append(c)
        for tag, cs in by_tag.items():
            groups.setdefault((tag, _product(r.d) or ""), []).append((r, cs))
    actions = []
    for (tag, product), hits in groups.items():
        if len(hits) < REPEAT:
            continue
        gain = sum(
            (total(checklist, {**r.ans, **{c.id: _top(c) for c in cs}}) or 0) - (r.total or 0)
            for r, cs in hits
        )
        up = r2(gain / n_all)
        owner = owners.get(tag, NOBODY)
        names = list(dict.fromkeys(c.name for _, cs in hits for c in cs))
        where = f" (продукт {product})" if product else ""
        hits.sort(key=lambda h: (h[0].total or 0, h[0].d.id))
        actions.append(
            _item(
                f"{VERB.get(owner, owner)}: {_dialogs(len(hits))} теряют баллы по причине „{tag}“{where}, "
                f"потенциальный рост среднего итога +{_d(up)}",
                f"Причина „{tag}“ снижала ответ по {'критерию' if len(names) == 1 else 'критериям'} "
                f"{', '.join(f'«{x}»' for x in names)} "
                f"в {len(hits)} из {n_all} оценённых диалогов; если бы там они были на максимуме, "
                f"средний итог вырос бы с {_d(avg)} до {_d(r2(avg + up))}.",
                ACTION_RULE,
                {
                    "dialogs": len(hits),
                    "scored": n_all,
                    "avg_total": r2(avg),
                    "uplift": up,
                    "criteria": names,
                    "channels": dict(Counter(r.d.ch for r, _ in hits)),
                },
                [
                    {"id": r.d.id, "cid": cs[0].id, "lines": sorted({n for c in cs for n in _ev(r, c)})}
                    for r, cs in hits[:BASIS]
                ],
                kind="reason",
                owner=owner,
                tag=tag,
                product=product or None,
                uplift=up,
            )
        )
    actions.sort(
        key=lambda a: (-a["uplift"], -a["basis"]["numbers"]["dialogs"], a["tag"], a["product"] or "")
    )

    by_op: dict[str, list[_Row]] = {}
    for r in rows:
        if op := _op(r.d):
            by_op.setdefault(op, []).append(r)
    operators = []
    for op in sorted(by_op):
        g = by_op[op]
        a = mean(r.total or 0 for r in g)
        gross = [(r, c) for r in g for c, _ in _flags(checklist, r)]
        low = avg - a >= ATTENTION_GAP
        if low and len(g) < MIN_N:
            insufficient.append(_short(op, len(g), MIN_N))
            low = False
        if not (low or gross):
            continue
        parts = [f"грубые нарушения в {_dialogs(len({r.d.id for r, _ in gross}))}"] if gross else []
        if low:
            parts.append(f"средний итог {_d(a)} ниже среднего по набору {_d(avg)} на {_d(avg - a)}")
        refs: list[dict[str, Any]] = [{"id": r.d.id, "cid": c.id, "lines": _ev(r, c)} for r, c in gross]
        refs += [
            {"id": r.d.id, "lines": _lost_lines(checklist, r)}
            for r in sorted(g, key=lambda r: (r.total or 0, r.d.id))
        ]
        uniq: dict[str, dict[str, Any]] = {}
        for x in refs:
            uniq.setdefault(x["id"], x)  # грубые нарушения первыми, затем худшие итоги
        operators.append(
            _item(
                f"{op}: нужен разбор с наставником",
                f"У сотрудника {op} {'; '.join(parts)} ({_dialogs(len(g))} оценено).",
                ATTENTION_RULE,
                {
                    "dialogs": len(g),
                    "avg_total": r2(a),
                    "team_avg_total": r2(avg),
                    "gap": r2(avg - a),
                    "gross": len(gross),
                },
                list(uniq.values())[:BASIS],
                operator=op,
            )
        )
    operators.sort(
        key=lambda o: (-o["basis"]["numbers"]["gross"], o["basis"]["numbers"]["avg_total"], o["operator"])
    )

    trends, short = _trends(checklist, rows, tuple(DIMS))
    return {
        "for": "manager",
        "params": _params("MIN_N", "REPEAT", "ATTENTION_GAP", "TREND_DROP"),
        "actions": actions,
        "operators": operators,
        "trends": [{k: v for k, v in t.items() if k != "late"} for t in trends],
        "insufficient": insufficient + short,
    }


# --- Автору чек-листа ---

KINDS = ("ambiguous", "weight", "na", "uniform")


def for_checklist(
    checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]
) -> dict[str, Any]:
    rows = _rows(checklist, dialogs, appeals)
    decisions = [a for a in appeals if a.status in ("confirmed", "changed")]
    by_id = {r.d.id: r for r in rows}
    scored_cs = _scored(checklist)
    items: list[tuple[tuple[int, int], dict[str, Any]]] = []
    insufficient: list[dict[str, Any]] = []

    def add(
        kind: str,
        i: int,
        c: Criterion,
        title: str,
        why: str,
        rule: str,
        numbers: dict[str, Any],
        refs: list[dict[str, Any]],
    ) -> None:
        items.append(
            (
                (KINDS.index(kind), i),
                _item(title, why, rule, numbers, refs[:BASIS], kind=kind, cid=c.id, name=c.name),
            )
        )

    loss: dict[str, float] = {c.id: 0.0 for c in scored_cs}
    lost: dict[str, list[_Row]] = {c.id: [] for c in scored_cs}
    for r in rows:
        if r.total is None:
            continue
        w = sum(c.w for c in scored_cs if _f(c, r) is not None)
        for c in scored_cs:
            if (f := _f(c, r)) is not None and f < 1:
                loss[c.id] += 100 * c.w * (1 - f) / w
                lost[c.id].append(r)
    sum_loss, sum_w = sum(loss.values()), sum(c.w for c in scored_cs)

    for i, c in enumerate(scored_cs):
        answered = [r for r in rows if c.id in r.ans]
        n = len(answered)
        if not n:
            continue
        ref = [{"id": r.d.id, "cid": c.id, "lines": _ev(r, c)} for r in answered]

        top, k = Counter(_say(r.ans[c.id]) for r in answered).most_common(1)[0]
        if k / n >= UNIFORM_SHARE:
            if n < MIN_UNIFORM:
                insufficient.append(_short(f"«{c.name}», одинаковые ответы", n, MIN_UNIFORM))
            else:
                odd = [x for x, r in zip(ref, answered, strict=True) if _say(r.ans[c.id]) != top]
                add(
                    "uniform",
                    i,
                    c,
                    f"«{c.name}»: {_pct(k / n)} оценок — «{top}». Проверьте, нужен ли критерий "
                    "или его формулировка",
                    f"Из {n} оценок {k} одинаковые («{top}»), критерий почти не различает диалоги.",
                    f"Один ответ у ≥ {_pct(UNIFORM_SHARE)} оценок при n ≥ {MIN_UNIFORM}; флаги грубых "
                    "нарушений не проверяются — они редки по замыслу.",
                    {"answers": n, "top": top, "same": k, "top_share": round(k / n, 4)},
                    odd + ref,
                )

        mine = [a for a in decisions if a.cid == c.id and a.dlg in by_id]
        second = [r for r in answered if r.d.res[c.id].alt is not None]
        measures: list[tuple[str, str, str, Sequence[Any], Sequence[Any]]] = [
            (
                "decided",
                "changed",
                "решений по апелляциям и проверкам изменили ответ",
                mine,
                [a for a in mine if a.status == "changed"],
            ),
            (
                "second",
                "disagree",
                "ответов второе мнение разошлось с основным",
                second,
                [r for r in second if r.d.res[c.id].alt != r.d.res[c.id].a],
            ),
            (
                "answers",
                "manual",
                "ответов исправлены вручную",
                answered,
                [r for r in answered if r.d.res[c.id].model == MANUAL],
            ),
        ]
        numbers: dict[str, Any] = {}
        parts: list[str] = []
        refs = []
        for base, hit, words, of, got in measures:
            numbers |= {base: len(of), hit: len(got)}
            if not of or len(got) / len(of) < DISPUTE_SHARE:
                continue
            if len(of) < MIN_N:
                insufficient.append(_short(f"«{c.name}», {words}", len(of), MIN_N))
                continue
            parts.append(f"{len(got)} из {len(of)} {words} ({_pct(len(got) / len(of))})")
            for x in got:
                if isinstance(x, Appeal):
                    refs.append({"id": x.dlg, "cid": c.id, "lines": list(x.ev) or _ev(by_id[x.dlg], c)})
                else:
                    refs.append({"id": x.d.id, "cid": c.id, "lines": _ev(x, c)})
        if parts:
            add(
                "ambiguous",
                i,
                c,
                f"«{c.name}»: формулировка неоднозначна — уточните текст и примеры",
                f"{'; '.join(parts)}.",
                f"Доля спорных оценок ≥ {_pct(DISPUTE_SHARE)} хотя бы по одной мере при её n ≥ {MIN_N}: "
                "решения, изменившие ответ; расхождение второго мнения; ручные исправления.",
                numbers,
                refs,
            )

        if c.na:
            nas = [x for x, r in zip(ref, answered, strict=True) if r.ans[c.id] == "na"]
            if len(nas) / n >= NA_SHARE:
                if n < MIN_N:
                    insufficient.append(_short(f"«{c.name}», N/A", n, MIN_N))
                else:
                    add(
                        "na",
                        i,
                        c,
                        f"«{c.name}»: N/A в {_pct(len(nas) / n)} оценок — проверьте условие N/A",
                        f"N/A поставлен в {len(nas)} из {n} оценок; условие: «{c.naCond or 'не задано'}».",
                        f"Доля N/A ≥ {_pct(NA_SHARE)} при n ≥ {MIN_N}.",
                        {"answers": n, "na": len(nas), "na_share": round(len(nas) / n, 4)},
                        nas,
                    )

        if sum_loss and loss[c.id] and (ls := loss[c.id] / sum_loss) >= WEIGHT_RATIO * (ws := c.w / sum_w):
            if len(lost[c.id]) < MIN_N:
                insufficient.append(_short(f"«{c.name}», вес", len(lost[c.id]), MIN_N))
            else:
                worst = sorted(lost[c.id], key=lambda r: (_f(c, r) or 0, r.d.id))
                add(
                    "weight",
                    i,
                    c,
                    f"«{c.name}»: вес {c.w:g} ({_pct(ws)} суммы весов), но критерий объясняет "
                    f"{_pct(ls)} потерь баллов — рассмотрите вес ≈{round(ls * sum_w)}",
                    f"Потери баллов по критерию — {_pct(ls)} всех потерь в {len(lost[c.id])} диалогах, "
                    f"а его вес — {_pct(ws)} суммы весов.",
                    "Потеря критерия в диалоге = 100 × вес × (1 − доля) / сумма весов "
                    "применимых критериев (сумма потерь = 100 − итог). Пункт, если доля потерь ≥ "
                    f"{WEIGHT_RATIO} × доля веса при ≥ {MIN_N} диалогах с потерей; "
                    "предложенный вес = доля потерь × сумма весов.",
                    {
                        "weight": c.w,
                        "weight_share": round(ws, 4),
                        "loss_share": round(ls, 4),
                        "dialogs": len(lost[c.id]),
                        "suggested_w": round(ls * sum_w),
                    },
                    [{"id": r.d.id, "cid": c.id, "lines": _ev(r, c)} for r in worst],
                )

    return {
        "for": "checklist",
        "params": _params(
            "MIN_N", "MIN_UNIFORM", "UNIFORM_SHARE", "DISPUTE_SHARE", "NA_SHARE", "WEIGHT_RATIO"
        ),
        "items": [it for _, it in sorted(items, key=lambda x: x[0])],
        "insufficient": insufficient,
    }
