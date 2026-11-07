"""make eval: два прогона оценщика по эталону, метрики, пороги и лучший прогон (eval-and-delivery)."""

import asyncio
import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, fields

import yaml

from cqa.domain.agreement import (
    Disagreement,
    GoldLabel,
    Report,
    RunMetrics,
    Thresholds,
    score_run,
    stability,
)
from cqa.domain.models import Checklist, CriterionResult, Dialog
from cqa.services.ports import Evaluator


def load_thresholds(text: str) -> Thresholds:
    """Пороги из eval/thresholds.yaml; неизвестный или пропущенный ключ — ValueError."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("thresholds.yaml: ожидается словарь порогов")
    names = {f.name for f in fields(Thresholds)}
    if unknown := sorted(set(data) - names):
        raise ValueError(f"thresholds.yaml: неизвестные пороги {', '.join(unknown)}")
    if missing := sorted(names - set(data)):
        raise ValueError(f"thresholds.yaml: нет порогов {', '.join(missing)}")
    return Thresholds(**{k: float(v) for k, v in data.items()})


@dataclass(frozen=True)
class _Run:
    results: dict[str, dict[str, CriterionResult]]
    verifier_usd: float
    verifier_calls: int
    seconds: float


async def _run(dialogs: Sequence[Dialog], checklist: Checklist, evaluator: Evaluator) -> _Run:
    start = time.monotonic()
    outs = await asyncio.gather(*(evaluator.evaluate(d, checklist, checklist.criteria) for d in dialogs))
    return _Run(
        results={d.id: {e.cid: e.result for e in out.results} for d, out in zip(dialogs, outs, strict=True)},
        verifier_usd=sum(out.verifier_usd for out in outs),
        verifier_calls=sum(out.verifier_calls for out in outs),
        seconds=time.monotonic() - start,
    )


def _worst(values: Iterable[float | None], pick: Callable[[list[float]], float] = min) -> float | None:
    defined = [v for v in values if v is not None]
    return pick(defined) if defined else None


def _worst_by_key(maps: list[dict[str, float | None]]) -> dict[str, float | None]:
    keys = dict.fromkeys(k for m in maps for k in m)
    return {k: _worst(m.get(k) for m in maps) for k in keys}


def _disagreements(metrics: list[RunMetrics]) -> list[Disagreement]:
    seen: dict[str, Disagreement] = {}
    for m in metrics:
        for d in m.disagreements:
            seen.setdefault(json.dumps([d.dlg, d.cid, d.got], sort_keys=True), d)
    return list(seen.values())


async def run_eval(
    dialogs: list[Dialog], gold: list[GoldLabel], checklist: Checklist, evaluator: Evaluator
) -> Report:
    """Два прогона прямыми вызовами evaluate только по диалогам эталона; худший прогон для порогов."""
    ids = {g.dlg for g in gold}
    chosen = [d for d in dialogs if d.id in ids]
    by_id = {d.id: d for d in chosen}
    runs = [await _run(chosen, checklist, evaluator) for _ in range(2)]
    metrics = [score_run(gold, r.results, by_id, checklist) for r in runs]
    first = metrics[0]
    return Report(
        agree_total=_worst(m.agree_total.frac for m in metrics),
        per_lang=_worst_by_key([{k: a.frac for k, a in m.per_lang.items()} for m in metrics]),
        per_cid=_worst_by_key([{k: a.frac for k, a in m.per_cid.items()} for m in metrics]),
        missing=max(m.missing for m in metrics),
        kz_gap_pts=_worst((m.kz_gap_pts for m in metrics), max),
        gross_recall=_worst_by_key([m.gross.recall for m in metrics]),
        gross_recall_lang=_worst_by_key([m.gross.by_lang for m in metrics]),
        gross_missed=sorted({miss for m in metrics for miss in m.gross.missed}),
        na_precision=_worst(m.na.precision for m in metrics),
        na_recall=_worst(m.na.recall for m in metrics),
        stability=stability(runs[0].results, runs[1].results),
        evidence_ok=min(m.evidence_ok for m in metrics),
        cost=first.cost + runs[0].verifier_usd,
        calls=first.calls + runs[0].verifier_calls,
        seconds=runs[0].seconds,
        n_dialogs=first.n_dialogs,
        model=first.model,
        false_flags=max(m.gross.false_flags for m in metrics),
        tags=first.tags,
        verifier=first.verifier,
        disagreements=_disagreements(metrics),
    )
