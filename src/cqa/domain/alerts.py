"""Маркеры диалогов и правила алертов. Чистые функции.

Каждый автоматический маркер и каждое срабатывание правила несёт `basis`: откуда вывод (правило, порог,
наблюдённое значение, диалоги, реплики, критерии, решения) и фраза `why` «Почему: …». Точные правила
(флаг отмечен и не отменён решением, апелляция ждёт решения) важнее порогов; порог — явный параметр
правила со значением по умолчанию и обоснованием `why`, которое хранится вместе с правилом.
Текста реплик в `basis` и заголовках нет: только номера реплик, id и подписи из чек-листа.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from cqa.domain.models import Answer, Appeal, Checklist, Criterion, Dialog, Line
from cqa.domain.prosody import LONG_PAUSE_S, RAISED_DB, RAISED_ST
from cqa.domain.review import ASTANA, effective_answer, needs_review
from cqa.domain.scoring import frac, r2, total

Severity = Literal["info", "warning", "critical"]
Kind = Literal[
    "gross_error",
    "low_total",
    "operator_avg",
    "no_next_step_share",
    "raised_tone",
    "appeal_overdue",
    "run_errors",
    "marker",
]
SEVERITIES = ("info", "warning", "critical")
STATUSES = ("new", "ack", "resolved")
# переход статуса алерта -> из каких статусов можно
MOVES: dict[str, tuple[str, ...]] = {"ack": ("new",), "resolved": ("new", "ack")}
CATALOG = ["Жалоба", "Эскалация", "VIP-клиент", "Для обучения", "Повторное обращение"]
LABEL = {
    "gross": "Грубое нарушение",
    "no_next_step": "Нет следующего шага",
    "raised_tone": "Клиент повысил тон",
    "long_pause": "Долгая пауза",
    "needs_review": "Нужна проверка",
    "appeal": "Апелляция",
    "low_total": "Низкий итог",
}
Basis = dict[str, Any]
Run = tuple[int, str, list[str]]  # id, статус, ошибки запуска


@dataclass(frozen=True)
class Param:
    name: str  # по-русски, для сообщений об ошибке
    default: float
    lo: float
    hi: float
    integer: bool = False


PARAMS: dict[str, dict[str, Param]] = {
    "gross_error": {},
    "low_total": {"threshold": Param("Порог итога", 60, 0, 100)},
    "operator_avg": {
        "n": Param("Число последних диалогов", 5, 1, 1000, integer=True),
        "threshold": Param("Порог среднего итога", 70, 0, 100),
        "min_dialogs": Param("Минимум диалогов", 3, 1, 1000, integer=True),
    },
    "no_next_step_share": {
        "threshold": Param("Порог доли, %", 30, 0, 100),
        "min_dialogs": Param("Минимум оценённых диалогов", 5, 1, 100000, integer=True),
    },
    "raised_tone": {},
    "appeal_overdue": {"hours": Param("Часов на рассмотрение", 24, 1, 8760)},
    "run_errors": {},
    "marker": {},  # label — строка из списка маркеров, проверяется отдельно
}


class AlertRule(BaseModel):
    id: str
    title: str
    kind: Kind
    params: dict[str, int | float | str] = {}
    severity: Severity
    enabled: bool = True
    why: str = ""  # обоснование правила и его порогов, показывается в интерфейсе


DEFAULT_RULES = [
    AlertRule(
        id="gross",
        title="Грубое нарушение",
        kind="gross_error",
        severity="critical",
        why="Точное правило: флаг чек-листа отмечен моделью или решением и не отменён решением.",
    ),
    AlertRule(
        id="low-total",
        title="Низкий итог",
        kind="low_total",
        params={"threshold": 60},
        severity="warning",
        why="60 из 100 — нижняя граница «удовлетворительно»; поменяйте под норматив центра.",
    ),
    AlertRule(
        id="operator-avg",
        title="Средний итог оператора",
        kind="operator_avg",
        params={"n": 5, "threshold": 70, "min_dialogs": 3},
        severity="warning",
        why="Среднее по 5 последним диалогам сглаживает случайный звонок; 70 — целевой уровень, "
        "меньше 3 диалогов не судим.",
    ),
    AlertRule(
        id="no-next-step",
        title="Доля диалогов без следующего шага",
        kind="no_next_step_share",
        params={"threshold": 30, "min_dialogs": 5},
        severity="warning",
        why="Каждый третий диалог без следующего шага — проблема процесса, а не оператора; "
        "на 5 диалогах и меньше доля неустойчива.",
    ),
    AlertRule(
        id="raised-tone",
        title="Клиент повысил тон",
        kind="raised_tone",
        severity="info",
        why=f"По звуку записи: тон клиента на {RAISED_ST:g} полутона выше или на {RAISED_DB:g} дБ громче "
        "его обычной манеры в этом же звонке.",
    ),
    AlertRule(
        id="appeal-overdue",
        title="Апелляция без решения",
        kind="appeal_overdue",
        params={"hours": 24},
        severity="warning",
        why="Апелляция дольше рабочих суток задерживает обратную связь оператору.",
    ),
    AlertRule(
        id="run-errors",
        title="Ошибки запуска оценки",
        kind="run_errors",
        severity="warning",
        why="Точное правило: пары без ответа модели не входят в итог, пока запуск не повторят.",
    ),
    AlertRule(
        id="complaint",
        title="Жалоба клиента",
        kind="marker",
        params={"label": "Жалоба"},
        severity="critical",
        why="Точное правило: маркер «Жалоба» поставлен вручную; жалобу разбирают в тот же день.",
    ),
]


def _n(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _join(xs: Sequence[object]) -> str:
    return ", ".join(map(str, xs))


# --- проверка правил ---


def check_rules(raw: Any, catalog: Sequence[str]) -> tuple[list[AlertRule], list[dict[str, Any]]]:
    """Правила из тела `PUT /api/alerts/rules`: недостающие параметры — по умолчанию. Ошибки — по полям."""
    if not isinstance(raw, list):
        return [], [{"loc": ["body"], "msg": "Нужен список правил"}]
    errors: list[dict[str, Any]] = []
    rules: list[AlertRule] = []
    seen: set[str] = set()
    for i, r in enumerate(raw):
        before = len(errors)

        def err(*loc: str, msg: str, i: int = i) -> None:
            errors.append({"loc": ["body", i, *loc], "msg": msg})

        if not isinstance(r, dict):
            err(msg="Правило — объект {id, title, kind, params, severity, enabled, why}")
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid.strip():
            err("id", msg="id — непустая строка")
        elif rid in seen:
            err("id", msg=f"id «{rid}» повторяется")
        else:
            seen.add(rid)
        if not isinstance(r.get("title"), str) or not r["title"].strip():
            err("title", msg="Название обязательно")
        if r.get("severity") not in SEVERITIES:
            err("severity", msg="Важность — info, warning или critical")
        if not isinstance(r.get("enabled", True), bool):
            err("enabled", msg="enabled — true или false")
        kind = r.get("kind")
        if kind not in PARAMS:
            err("kind", msg=f"Вид правила — один из: {_join(list(PARAMS))}")
            continue
        params = r.get("params") or {}
        if not isinstance(params, dict):
            err("params", msg="params — объект")
            continue
        spec, clean = PARAMS[kind], {}
        for k in params:
            if k not in spec and not (kind == "marker" and k == "label"):
                err("params", k, msg=f"У правила {kind} нет параметра {k}")
        for k, p in spec.items():
            v = params.get(k, p.default)
            ok = isinstance(v, int | float) and not isinstance(v, bool) and p.lo <= v <= p.hi
            if not ok or (p.integer and not float(v).is_integer()):
                whole = "целое " if p.integer else ""
                err("params", k, msg=f"{p.name}: {whole}число от {_n(p.lo)} до {_n(p.hi)}")
            else:
                clean[k] = int(v) if p.integer or float(v).is_integer() else v
        if kind == "marker":
            label = params.get("label")
            if label not in catalog:
                err("params", "label", msg=f"Маркера «{label}» нет в списке маркеров: {_join(catalog)}")
            else:
                clean["label"] = label
        why = r.get("why", "")
        if not isinstance(why, str):
            err("why", msg="Обоснование — строка")
        elif spec and not why.strip():
            err("why", msg="Обоснование порога обязательно: одна строка, почему такое значение")
        if len(errors) == before:
            rules.append(AlertRule.model_validate({**r, "params": clean}))
    return rules, errors


# --- маркеры диалога ---


@dataclass(frozen=True)
class DialogView:
    """Диалог для правил: итог с учётом решений и маркеры с обоснованием."""

    id: str
    operator: str | None
    total: float | None
    markers: list[dict[str, Any]]


def _decision(mine: Sequence[Appeal], cid: str) -> Appeal | None:
    """Последнее решение пары (как `effective_answer`): от него ответ, иначе от модели."""
    done = [a for a in mine if a.cid == cid and a.status in ("confirmed", "changed") and a.to is not None]
    return done[-1] if done else None


def _source(mine: Sequence[Appeal], cid: str) -> str:
    d = _decision(mine, cid)
    return f"подтверждено решением {d.id}" if d else "зафиксировано моделью, решением не отменено"


def _top(c: Criterion) -> Answer:
    return max(c.steps or [0]) if c.type == "scale" else "yes"


def _lines_of(prosody: Mapping[str, Any] | None, flag: str) -> list[dict[str, Any]]:
    return [ln for ln in (prosody or {}).get("lines", []) if flag in (ln.get("flags") or [])]


def _auto(k: str, basis: Basis) -> dict[str, Any]:
    return {"k": k, "label": LABEL[k], "auto": True, "basis": basis}


def dialog_view(
    checklist: Checklist,
    d: Dialog,
    appeals: Sequence[Appeal],
    *,
    prosody: Mapping[str, Any] | None,
    manual: Sequence[Mapping[str, str]],
    low: AlertRule | None,
) -> DialogView:
    """`appeals` — как в GET /api/state; `prosody` — сохранённая интонация звонка; `low` — правило
    `low_total`, чей порог даёт маркер «Низкий итог» (нет правила — нет маркера)."""
    mine = [a for a in appeals if a.dlg == d.id]
    ans = {cid: effective_answer(r, [a for a in mine if a.cid == cid]) for cid, r in d.res.items()}
    out: list[dict[str, Any]] = []

    def ev(cids: Sequence[str]) -> list[int]:
        return sorted({n for cid in cids for n in d.res[cid].ev})

    gross = [
        (c, [q for q in c.questions or [] if a.get(q.k)])
        for c in checklist.criteria
        if c.type == "flag" and isinstance(a := ans.get(c.id), dict)
    ]
    gross = [(c, qs) for c, qs in gross if qs]
    if gross:
        cids = [c.id for c, _ in gross]
        lines = ev(cids)
        parts = "; ".join(
            f"«{_join([q.label for q in qs])}» по критерию {c.id} — {_source(mine, c.id)}" for c, qs in gross
        )
        where = f", реплики {_join(lines)}" if lines else ""
        out.append(
            _auto(
                "gross",
                {
                    "criteria": cids,
                    "flags": [q.k for _, qs in gross for q in qs],
                    "lines": lines,
                    "appeals": [dec.id for cid in cids if (dec := _decision(mine, cid))],
                    "why": f"Почему: {parts}{where}.",
                },
            )
        )

    lost = [
        (c, a)
        for c in checklist.criteria
        if c.signal == "resolution"
        and (a := ans.get(c.id)) is not None
        and (f := frac(c, a)) is not None
        and f < 1
    ]
    if lost:
        cids = [c.id for c, _ in lost]
        parts = "; ".join(
            f"по критерию {c.id} «{c.name}» ответ {a} при верхней ступени {_top(c)} ({_source(mine, c.id)})"
            for c, a in lost
        )
        out.append(
            _auto(
                "no_next_step",
                {
                    "criteria": cids,
                    "answers": {c.id: a for c, a in lost},
                    "top": {c.id: _top(c) for c, _ in lost},
                    "lines": ev(cids),
                    "why": f"Почему: {parts}.",
                },
            )
        )

    who = {ln.n: ln.who for ln in d.lines or [] if isinstance(ln, Line)}
    raised = [ln["n"] for ln in _lines_of(prosody, "raised") if who.get(ln["n"]) == "client"]
    if raised:
        out.append(
            _auto(
                "raised_tone",
                {
                    "lines": raised,
                    "why": f"Почему: по звуку записи тон клиента на {_n(RAISED_ST)} полутона выше или на "
                    f"{_n(RAISED_DB)} дБ громче его обычной манеры в этом звонке, реплики {_join(raised)}.",
                },
            )
        )
    pauses = _lines_of(prosody, "long_pause")
    if pauses:
        longest = max(ln.get("pause") or 0 for ln in pauses)
        out.append(
            _auto(
                "long_pause",
                {
                    "lines": [ln["n"] for ln in pauses],
                    "value": longest,
                    "threshold": LONG_PAUSE_S,
                    "why": f"Почему: оператор ответил клиенту после тишины до {_n(longest)} с "
                    f"(порог {_n(LONG_PAUSE_S)} с), реплики {_join([ln['n'] for ln in pauses])}.",
                },
            )
        )

    review = [
        (c, r)
        for c in checklist.criteria
        if not d.reviewed
        and (r := d.res.get(c.id)) is not None
        and needs_review(c, r)
        and _decision(mine, c.id) is None
    ]
    if review:
        parts = "; ".join(
            f"{c.id} — модели расходятся: {r.a} и {r.alt}"
            if r.alt is not None and r.alt != r.a
            else f"{c.id} — основание не найдено в расшифровке"
            for c, r in review
        )
        out.append(
            _auto(
                "needs_review",
                {
                    "criteria": [c.id for c, _ in review],
                    "why": f"Почему: {parts}; решения нет, диалог не отмечен проверенным.",
                },
            )
        )

    pending = [a for a in mine if a.kind == "appeal" and a.status == "pending"]
    if pending:
        parts = "; ".join(f"апелляция {a.id} по критерию {a.cid} ждёт решения с {a.at}" for a in pending)
        out.append(
            _auto(
                "appeal",
                {
                    "appeals": [a.id for a in pending],
                    "criteria": [a.cid for a in pending],
                    "why": f"Почему: {parts}.",
                },
            )
        )

    t = total(checklist, ans)
    if low is not None and t is not None and t < (thr := float(low.params["threshold"])):
        out.append(
            _auto(
                "low_total",
                {
                    "rule": low.id,
                    "threshold": low.params["threshold"],
                    "value": t,
                    "why": f"Почему: итог {_n(t)} с учётом решений ниже порога {_n(thr)} "
                    f"правила «{low.title}».",
                },
            )
        )

    out += [
        {"k": m["label"], "label": m["label"], "auto": False, "by": m["by"], "at": m["at"]} for m in manual
    ]
    return DialogView(d.id, getattr(d, "operator", None), t, out)


# --- правила алертов ---


def _age_hours(at: str, now: datetime) -> float:
    """`at` апелляции — «ДД.ММ ЧЧ:ММ» по Астане без года: год текущий, будущая дата — прошлый год."""
    t = datetime.strptime(f"{now.year}.{at}", "%Y.%d.%m %H:%M").replace(tzinfo=ASTANA)
    if t > now:
        t = t.replace(year=now.year - 1)
    return (now - t).total_seconds() / 3600


def _fire(
    rule: AlertRule,
    views: Sequence[DialogView],
    appeals: Sequence[Appeal],
    runs: Sequence[Run],
    now: datetime,
) -> Iterator[tuple[str, str, str, Basis]]:
    """(target_type, target_id, подпись цели, basis) для каждого срабатывания правила."""
    p = rule.params

    def num(k: str) -> float:
        return float(p[k])

    def by_marker(k: str) -> Iterator[tuple[str, str, str, Basis]]:
        for v in views:
            m = next((m for m in v.markers if m["auto"] and m["k"] == k), None)
            if m is not None:
                yield "dialog", v.id, f"диалог {v.id}", {"dialogs": [v.id], **m["basis"]}

    if rule.kind == "gross_error":
        yield from by_marker("gross")
    elif rule.kind == "raised_tone":
        yield from by_marker("raised_tone")
    elif rule.kind == "marker":
        for v in views:
            m = next((m for m in v.markers if not m["auto"] and m["label"] == p["label"]), None)
            if m is not None:
                why = f"Почему: {m['by']} поставил маркер «{m['label']}» {m['at']}."
                yield "dialog", v.id, f"диалог {v.id}", {"dialogs": [v.id], "marker": m["label"], "why": why}
    elif rule.kind == "low_total":
        for v in views:
            if v.total is not None and v.total < num("threshold"):
                why = f"Почему: итог {_n(v.total)} с учётом решений ниже порога {_n(num('threshold'))}."
                basis = {"dialogs": [v.id], "threshold": p["threshold"], "value": v.total, "why": why}
                yield "dialog", v.id, f"диалог {v.id}", basis
    elif rule.kind == "operator_avg":
        groups: dict[str, list[DialogView]] = {}
        for v in views:
            if v.operator and v.total is not None:
                groups.setdefault(v.operator, []).append(v)
        for op, vs in groups.items():
            last = vs[-int(num("n")) :]
            if len(last) < num("min_dialogs"):
                continue
            avg = r2(sum(v.total or 0 for v in last) / len(last))
            if avg < num("threshold"):
                why = (
                    f"Почему: средний итог {_n(avg)} по последним {len(last)} оценённым диалогам оператора "
                    f"ниже порога {_n(num('threshold'))}."
                )
                basis = {
                    "dialogs": [v.id for v in last],
                    "threshold": p["threshold"],
                    "value": avg,
                    "why": why,
                }
                yield "operator", op, f"оператор {op}", basis
    elif rule.kind == "no_next_step_share":
        scored = [v for v in views if v.total is not None]
        if scored and len(scored) >= num("min_dialogs"):
            hit = [v.id for v in scored if any(m["auto"] and m["k"] == "no_next_step" for m in v.markers)]
            share = round(100 * len(hit) / len(scored), 1)
            if share > num("threshold"):
                why = (
                    f"Почему: без следующего шага {len(hit)} из {len(scored)} оценённых диалогов — "
                    f"{_n(share)} %, порог {_n(num('threshold'))} %."
                )
                basis = {"dialogs": hit, "threshold": p["threshold"], "value": share, "why": why}
                yield "set", "all", f"{_n(share)} % набора", basis
    elif rule.kind == "appeal_overdue":
        for a in appeals:
            if a.kind == "appeal" and a.status == "pending" and (age := _age_hours(a.at, now)) > num("hours"):
                why = (
                    f"Почему: апелляция {a.id} по критерию {a.cid} подана {a.at} и ждёт решения "
                    f"{_n(round(age, 1))} ч, порог {_n(num('hours'))} ч."
                )
                basis = {
                    "appeals": [a.id],
                    "dialogs": [a.dlg],
                    "criteria": [a.cid],
                    "threshold": p["hours"],
                    "value": round(age, 1),
                    "why": why,
                }
                yield "appeal", a.id, f"апелляция {a.id}", basis
    elif rule.kind == "run_errors":
        for run_id, status, errors in runs:
            if status == "done" and errors:
                # текст ошибки не берём: в нём может быть ответ модели; только id диалогов
                ids = list(dict.fromkeys(e.split(":")[0].split("/")[0] for e in errors))
                why = f"Почему: запуск {run_id} завершён, ошибок {len(errors)}: эти пары не входят в итог."
                yield (
                    "run",
                    str(run_id),
                    f"запуск {run_id}",
                    {"dialogs": ids, "value": len(errors), "why": why},
                )


def check_alerts(
    rules: Sequence[AlertRule],
    views: Sequence[DialogView],
    appeals: Sequence[Appeal],
    runs: Sequence[Run],
    now: datetime,
) -> list[dict[str, Any]]:
    """Срабатывания включённых правил: {rule_id, severity, title, target_type, target_id, basis}."""
    return [
        {
            "rule_id": rule.id,
            "severity": rule.severity,
            "title": f"{rule.title}: {label}",
            "target_type": target_type,
            "target_id": target_id,
            "basis": {"rule": rule.id, **basis},
        }
        for rule in rules
        if rule.enabled
        for target_type, target_id, label, basis in _fire(rule, views, appeals, runs, now)
    ]
