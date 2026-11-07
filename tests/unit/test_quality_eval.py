from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from cqa.domain.agreement import GoldLabel, Thresholds
from cqa.domain.models import Checklist, Criterion, CriterionResult, Dialog, DialogEvaluation, Evaluation
from cqa.services.quality_eval import load_thresholds, run_eval

ROOT = Path(__file__).resolve().parents[2]


def test_thresholds_file_holds_design_values() -> None:
    assert load_thresholds((ROOT / "eval/thresholds.yaml").read_text(encoding="utf-8")) == Thresholds(
        gross_recall_min=1.0,
        kz_gap_max_pts=5,
        na_precision_min=0.90,
        na_recall_min=0.90,
        stability_min=0.95,
        evidence_ok_min=0.92,
        holdout_agreement_min=0.85,
        baseline_drop_max_pts=3,
    )


def test_unknown_threshold_key_is_rejected() -> None:
    text = (ROOT / "eval/thresholds.yaml").read_text(encoding="utf-8") + "agree_min: 0.9\n"
    with pytest.raises(ValueError, match="agree_min"):
        load_thresholds(text)


def test_missing_threshold_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="stability_min"):
        load_thresholds("gross_recall_min: 1.0\n")


CHECKLIST = Checklist.model_validate_json(
    (ROOT / "tests/fixtures/checklist_v3.json").read_text(encoding="utf-8")
)


def chat(dlg: str, lang: str = "RU", ch: Any = "chat") -> Dialog:
    return Dialog(id=dlg, ch=ch, lang=lang, at="07.11 10:00", lines=[])


def res(a: Any, **fields: Any) -> CriterionResult:
    return CriterionResult(a=a, model="qwen3-6", calls=1, cost=0.0012, **fields)


class FakeEvaluator:
    """Ответы по прогонам: runs[i][dlg] — результаты i-го вызова evaluate этого диалога."""

    def __init__(self, runs: list[dict[str, dict[str, CriterionResult]]], verifier_usd: float = 0.0) -> None:
        self.runs = runs
        self.verifier_usd = verifier_usd
        self.calls: list[tuple[str, list[str]]] = []

    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        nth = sum(1 for dlg, _ in self.calls if dlg == dialog.id)
        self.calls.append((dialog.id, [c.id for c in criteria]))
        results = self.runs[min(nth, len(self.runs) - 1)].get(dialog.id, {})
        return DialogEvaluation(
            results=[Evaluation(cid, r) for cid, r in results.items()],
            verifier_calls=1 if self.verifier_usd else 0,
            verifier_usd=self.verifier_usd,
        )


def label(dlg: str, cid: str, *ok: Any) -> GoldLabel:
    return GoldLabel(dlg, cid, ok or None, "team", "")


async def test_run_eval_calls_evaluate_twice_per_gold_dialog_only() -> None:
    gold = [label("d1", "01", "yes"), label("d2", "01", "yes"), label("d3", "01")]
    fake = FakeEvaluator([{d: {"01": res("yes")} for d in ("d1", "d2", "d3", "extra")}])
    dialogs = [chat("d1"), chat("extra"), chat("d2"), chat("d3")]
    await run_eval(dialogs, gold, CHECKLIST, fake)
    assert sorted(d for d, _ in fake.calls) == ["d1", "d1", "d2", "d2", "d3", "d3"]
    assert all(cids == [c.id for c in CHECKLIST.criteria] for _, cids in fake.calls)


async def test_report_cost_is_results_plus_second_opinion_per_run() -> None:
    dialogs = [chat(f"d{i}") for i in range(20)]
    gold = [label(d.id, "01", "yes") for d in dialogs]
    answers = {d.id: {f"c{j}": res("yes") for j in range(10)} for d in dialogs}
    report = await run_eval(dialogs, gold, CHECKLIST, FakeEvaluator([answers], verifier_usd=0.001))
    assert report.cost == pytest.approx(0.24 + 0.02)
    assert report.calls == 200 + 20
    assert report.cost_per_dialog == pytest.approx(0.013)
    assert report.calls_per_dialog == 11
    assert report.model == "qwen3-6"
    assert report.n_dialogs == 20
    assert report.seconds >= 0


async def test_report_takes_worst_of_two_runs_and_measures_stability() -> None:
    dialogs = [chat("r1"), chat("r2"), chat("k1", "KZ"), chat("k2", "KZ")]
    gold = [label(d.id, "01", "yes") for d in dialogs] + [label("r1", "04", 15, 20)]
    first = {d.id: {"01": res("yes")} for d in dialogs} | {"r1": {"01": res("yes"), "04": res(20)}}
    second = first | {"k2": {"01": res("no", why="Не представился")}, "r1": {"01": res("yes")}}
    report = await run_eval(dialogs, gold, CHECKLIST, FakeEvaluator([first, second]))
    assert report.agree_total == pytest.approx(3 / 5)
    assert report.per_lang == {"RU": pytest.approx(2 / 3), "KZ": 0.5}
    assert report.per_cid == {"01": 0.75, "04": 0.0}
    assert report.missing == 1
    assert report.kz_gap_pts == pytest.approx(16.67)
    assert report.stability == pytest.approx(3 / 5)
    assert [(d.dlg, d.cid, d.got) for d in report.disagreements] == [("k2", "01", "no"), ("r1", "04", None)]
