from pathlib import Path

import pytest

from cqa.domain.agreement import Thresholds
from cqa.services.quality_eval import load_thresholds

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
