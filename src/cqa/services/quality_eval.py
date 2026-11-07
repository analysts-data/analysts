"""make eval: два прогона оценщика по эталону, метрики, пороги и лучший прогон (eval-and-delivery)."""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from collections.abc import Callable, Coroutine, Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cqa.compose import build_source
from cqa.domain.agreement import (
    Disagreement,
    GoldLabel,
    Report,
    RunMetrics,
    Thresholds,
    gate,
    load_gold,
    score_run,
    stability,
)
from cqa.domain.models import Checklist, Criterion, CriterionResult, Dialog
from cqa.domain.prompt import PROMPT_VERSION
from cqa.services.errors import ConfigError
from cqa.services.evaluation import RealDataBlocked
from cqa.services.ports import Evaluator
from cqa.settings import Settings

# пути от корня репозитория: make eval запускается из него
CHECKLIST = Path("tests/fixtures/checklist_v3.json")
GOLD = Path("eval/gold/labels.jsonl")
THRESHOLDS = Path("eval/thresholds.yaml")
BASELINE = Path("eval/baseline.json")
REPORTS = Path("eval/reports")
REPO = Path(__file__).resolve().parents[3]
# поля Report, по которым gate сравнивает с лучшим прогоном; в baseline.json только они, без текстов
_GATE = (
    "agree_total",
    "per_lang",
    "per_cid",
    "missing",
    "kz_gap_pts",
    "gross_recall",
    "gross_recall_lang",
    "gross_missed",
    "na_precision",
    "na_recall",
    "stability",
    "evidence_ok",
    "holdout_agreement",
)


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


def load_holdout(
    holdout_dir: Path, checklist: Checklist
) -> tuple[list[tuple[Criterion, str]], list[GoldLabel]]:
    """criteria.json: Criterion с полем replaces (id критерия чек-листа); labels.jsonl: формат эталона.

    Разметка проверяется по чек-листу, где заменённые критерии уступили место отложенным.
    """
    known = {c.id for c in checklist.criteria}
    criteria: list[tuple[Criterion, str]] = []
    for i, item in enumerate(
        json.loads((holdout_dir / "criteria.json").read_text(encoding="utf-8")), start=1
    ):
        body = dict(item)
        replaces = body.pop("replaces", None)
        if replaces not in known:
            raise ValueError(
                f"критерий {i}: replaces должен назвать критерий чек-листа, получено {replaces!r}"
            )
        try:
            criteria.append((Criterion.model_validate(body), replaces))
        except ValidationError as exc:
            raise ValueError(f"критерий {i}: {exc.error_count()} ошибок формы Criterion") from None
    ids = {c.id for c, _ in criteria}
    merged = checklist.model_copy(
        update={"criteria": [c for c in checklist.criteria if c.id not in ids] + [c for c, _ in criteria]}
    )
    lines = (holdout_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    return criteria, load_gold(lines, merged)


@dataclass(frozen=True)
class HoldoutRow:
    """Строка отчёта отложенных критериев: только идентификатор, тип и числа."""

    cid: str
    type: str
    n: int
    agree: float | None


@dataclass(frozen=True)
class HoldoutReport:
    rows: list[HoldoutRow]
    n: int
    hits: int

    @property
    def agreement(self) -> float | None:
        return None if self.n == 0 else self.hits / self.n


async def run_holdout(
    dialogs: list[Dialog], holdout_dir: Path, checklist: Checklist, evaluator: Evaluator
) -> HoldoutReport:
    """Каждый отложенный критерий встаёт на место replaces, оценка зовётся только по нему."""
    criteria, labels = load_holdout(holdout_dir, checklist)
    rows: list[HoldoutRow] = []
    total = hits_total = 0
    for criterion, replaces in criteria:
        swapped = checklist.model_copy(
            update={"criteria": [criterion if c.id == replaces else c for c in checklist.criteria]}
        )
        mine = [g for g in labels if g.cid == criterion.id and g.ok is not None]
        targets = [d for d in dialogs if d.id in {g.dlg for g in mine}]
        outs = await asyncio.gather(*(evaluator.evaluate(d, swapped, [criterion]) for d in targets))
        got = {d.id: {e.cid: e.result.a for e in out.results} for d, out in zip(targets, outs, strict=True)}
        hits = sum(1 for g in mine if g.ok and got.get(g.dlg, {}).get(criterion.id, None) in g.ok)
        rows.append(HoldoutRow(criterion.id, criterion.type, len(mine), hits / len(mine) if mine else None))
        total += len(mine)
        hits_total += hits
    return HoldoutReport(rows, total, hits_total)


def _build_evaluator(settings: Settings) -> Evaluator:
    from cqa.compose import build_evaluator  # local import keeps module import free of adapters

    evaluator: Evaluator = build_evaluator(settings)
    return evaluator


def _git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent, check=False
    )
    return out.stdout.strip()


def _load_baseline() -> Report | None:
    if not BASELINE.exists():
        return None
    data = json.loads(BASELINE.read_text(encoding="utf-8"))["report"]
    return Report(**{k: data[k] for k in _GATE} | {"gross_missed": [tuple(m) for m in data["gross_missed"]]})


def _num(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}".replace(".", ",")


def _table(report: Report) -> str:
    rows = [
        f"Совпадение: всего {_num(report.agree_total)}"
        + "".join(f" · {lang} {_num(v)}" for lang, v in report.per_lang.items())
        + f" · разрыв RU−KZ {_num(report.kz_gap_pts, 1)} п.",
        "По критериям: " + " · ".join(f"{cid} {_num(v)}" for cid, v in sorted(report.per_cid.items())),
        "Полнота флагов: "
        + " · ".join(f"{k} {_num(v)}" for k, v in report.gross_recall.items())
        + f" · ложных {report.false_flags}",
        f"N/A: точность {_num(report.na_precision)} · полнота {_num(report.na_recall)}",
        f"Стабильность {_num(report.stability)} · основания {_num(report.evidence_ok)}"
        f" · ждут оценки {report.missing} · расхождений {len(report.disagreements)}",
        f"Цена ${report.cost:.4f} · вызовов {report.calls} · на диалог ${report.cost_per_dialog or 0:.4f}"
        f" и {_num(report.calls_per_dialog, 1)} · {report.seconds:.0f} с · модель {report.model or '—'}",
    ]
    return "\n".join(rows)


class _Stop(Exception):
    """Ошибка конфигурации: main печатает текст и возвращает код 2 без вызовов оценщика."""


def _snapshot(settings: Settings, ids: set[str], *, quiet: bool = False) -> list[Dialog]:
    """Диалоги разметки из снимка CQA_EVAL_DATASET; звонок только с CQA_ALLOW_REAL_DATA=1.

    quiet: в сообщениях только число диалогов (отложенные критерии не раскрывают разметку).
    """
    if not settings.eval_dataset.exists():
        raise _Stop(f"Нет набора {settings.eval_dataset}: положите снимок DEV или задайте CQA_EVAL_DATASET")
    raw = settings.eval_dataset.read_bytes()
    dialogs = [d for d in build_source(settings).upload(raw).dialogs if d.id in ids]
    calls = sorted(d.id for d in dialogs if d.ch == "call")
    if calls and not settings.allow_real_data:
        named = f"{len(calls)}" if quiet else ", ".join(calls)
        raise _Stop(f"Звонки в разметке без CQA_ALLOW_REAL_DATA=1, оценка не запущена: {named}")
    if absent := sorted(ids - {d.id for d in dialogs}):
        named = f"{len(absent)}" if quiet else ", ".join(absent)
        print(f"Нет в снимке, пары считаются несовпадением: {named}")
    return dialogs


def _evaluate[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coro)
    except (ConfigError, RealDataBlocked) as exc:
        raise _Stop(f"Оценка не запущена: {exc}") from None


def _save(body: dict[str, Any], prefix: str = "") -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{prefix}{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _verdict(problems: list[str], path: Path) -> int:
    print("\n".join(f"НЕ ПРОШЛО: {p}" for p in problems) or "Все пороги пройдены")
    print(f"Отчёт: {path}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    """make eval и make eval-holdout: 0 — прошло, 1 — порог или регресс, 2 — ошибка конфигурации."""
    parser = argparse.ArgumentParser(prog="python -m cqa.services.quality_eval")
    parser.add_argument(
        "--checklist", type=Path, default=CHECKLIST, help="чек-лист или выгрузка GET /api/state"
    )
    parser.add_argument(
        "--accept", action="store_true", help="записать eval/baseline.json, если прогон прошёл"
    )
    parser.add_argument("--holdout", action="store_true", help="отложенные критерии из CQA_HOLDOUT_DIR")
    args = parser.parse_args(argv)

    settings = Settings()
    raw = json.loads(args.checklist.read_text(encoding="utf-8"))
    checklist = Checklist.model_validate(raw.get("checklist", raw))
    try:
        return (
            _holdout_main(settings, checklist)
            if args.holdout
            else _eval_main(settings, checklist, args.accept)
        )
    except _Stop as exc:
        print(exc)
        return 2


def _holdout_main(settings: Settings, checklist: Checklist) -> int:
    holdout = settings.holdout_dir
    if holdout is None or holdout.resolve().is_relative_to(REPO):
        raise _Stop("Отложенные критерии лежат вне репозитория: задайте CQA_HOLDOUT_DIR каталогом вне него")
    try:
        _, labels = load_holdout(holdout, checklist)
    except ValueError as exc:
        raise _Stop(f"Отложенные критерии: {exc}") from None
    dialogs = _snapshot(settings, {g.dlg for g in labels}, quiet=True)
    report = _evaluate(run_holdout(dialogs, holdout, checklist, _build_evaluator(settings)))
    limit = load_thresholds(THRESHOLDS.read_text(encoding="utf-8")).holdout_agreement_min
    problems = (
        [f"совпадение отложенных критериев {_num(report.agreement)} ниже {_num(limit)}"]
        if report.agreement is not None and report.agreement < limit
        else []
    )
    body = asdict(report) | {"agreement": report.agreement, "problems": problems}
    path = _save(body, "holdout-")
    for row in report.rows:
        print(f"{row.cid} ({row.type}): {row.n} ответов, совпадение {_num(row.agree)}")
    print(f"Отложенные критерии вместе: {_num(report.agreement)} ({report.hits} из {report.n})")
    return _verdict(problems, path)


def _eval_main(settings: Settings, checklist: Checklist, accept: bool) -> int:
    gold = load_gold(GOLD.read_text(encoding="utf-8").splitlines(), checklist)
    dialogs = _snapshot(settings, {g.dlg for g in gold})
    report = _evaluate(run_eval(dialogs, gold, checklist, _build_evaluator(settings)))
    problems = gate(report, load_thresholds(THRESHOLDS.read_text(encoding="utf-8")), _load_baseline())
    body: dict[str, Any] = asdict(report) | {
        "cost_per_dialog": report.cost_per_dialog,
        "calls_per_dialog": report.calls_per_dialog,
        "problems": problems,
    }
    path = _save(body)
    print(_table(report))
    if _verdict(problems, path):
        return 1
    if accept:
        baseline = {
            "report": {k: body[k] for k in _GATE},
            "model": report.model,
            "scenario": {
                "model": settings.llm_model,
                "profile": settings.llm_profile,
                "reasoning": settings.llm_reasoning,
                "verifier": settings.verifier,
                "anonymize": settings.anonymize,
            },
            "prompt_version": PROMPT_VERSION,
            "checklist_version": checklist.version,
            "git_sha": _git_sha(),
        }
        BASELINE.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Лучший прогон записан: {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
