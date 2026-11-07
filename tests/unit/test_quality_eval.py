import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from cqa.domain.agreement import GoldLabel, Thresholds
from cqa.domain.models import Checklist, Criterion, CriterionResult, Dialog, DialogEvaluation, Evaluation
from cqa.domain.prompt import PROMPT_VERSION
from cqa.services import quality_eval
from cqa.services.quality_eval import load_holdout, load_thresholds, run_eval

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


CHATS = ("syn-chat-ru", "syn-chat-kz", "syn-chat-en")


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пустой каталог с порогами, эталоном по синтетическим чатам и снимком в формате организаторов."""
    monkeypatch.chdir(tmp_path)
    for key in ("CQA_ALLOW_REAL_DATA", "CQA_LLM_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CQA_EVAL_DATASET", str(ROOT / "tests/fixtures/org_payload.json"))
    (tmp_path / "eval/gold").mkdir(parents=True)
    (tmp_path / "eval/thresholds.yaml").write_text(
        (ROOT / "eval/thresholds.yaml").read_text(encoding="utf-8")
    )
    write_gold(tmp_path, CHATS)
    return tmp_path


def write_gold(root: Path, dialogs: Sequence[str]) -> None:
    rows = [{"dlg": d, "cid": "01", "ok": ["yes"], "by": "team", "note": ""} for d in dialogs]
    (root / "eval/gold/labels.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def use(monkeypatch: pytest.MonkeyPatch, fake: FakeEvaluator) -> FakeEvaluator:
    monkeypatch.setattr(quality_eval, "_build_evaluator", lambda settings: fake)
    return fake


def answers(**got: Any) -> dict[str, dict[str, CriterionResult]]:
    return {d: {"01": got.get(d.replace("-", "_"), res("yes"))} for d in CHATS}


ARGS = ["--checklist", str(ROOT / "tests/fixtures/checklist_v3.json")]


def test_clean_run_returns_zero_and_saves_report(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main(ARGS) == 0
    [path] = (workdir / "eval/reports").glob("*.json")
    out = capsys.readouterr().out
    assert str(Path("eval/reports") / path.name) in out
    report = json.loads(path.read_text(encoding="utf-8"))
    assert (report["agree_total"], report["disagreements"], report["problems"]) == (1.0, [], [])
    assert report["cost"] == pytest.approx(0.0036) and report["calls_per_dialog"] == 1
    assert sorted(d for d, _ in fake.calls) == sorted(CHATS * 2)
    assert not (workdir / "eval/baseline.json").exists()


def test_call_in_gold_without_permission_returns_two_without_any_call(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_gold(workdir, [*CHATS, "syn-call-hold"])
    fake = use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main(ARGS) == 2
    assert "syn-call-hold" in capsys.readouterr().out
    assert fake.calls == []


def test_missing_dataset_returns_two(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_EVAL_DATASET", str(workdir / "нет.json"))
    fake = use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main(ARGS) == 2
    assert fake.calls == []


def test_kazakh_gap_returns_one_and_lists_disagreement(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    miss = res("no", why="Не представился", quote="Сәлеметсіз бе")
    use(monkeypatch, FakeEvaluator([answers(syn_chat_kz=miss)]))
    assert quality_eval.main(ARGS) == 1
    assert "разрыв RU−KZ" in capsys.readouterr().out
    [path] = (workdir / "eval/reports").glob("*.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["disagreements"] == [
        {
            "dlg": "syn-chat-kz",
            "cid": "01",
            "gold": ["yes"],
            "got": "no",
            "why": "Не представился",
            "quote": "Сәлеметсіз бе",
        }
    ]


def test_accept_writes_baseline_only_after_passing_run(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unstable = FakeEvaluator([answers(), answers(syn_chat_ru=res(20))])
    use(monkeypatch, unstable)
    assert quality_eval.main([*ARGS, "--accept"]) == 1
    assert not (workdir / "eval/baseline.json").exists()

    use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main([*ARGS, "--accept"]) == 0
    baseline = json.loads((workdir / "eval/baseline.json").read_text(encoding="utf-8"))
    assert baseline["report"]["agree_total"] == 1.0
    assert baseline["prompt_version"] == PROMPT_VERSION and baseline["checklist_version"] == 3
    assert {"model", "scenario", "git_sha"} <= set(baseline)
    assert "disagreements" not in baseline["report"]


def test_drop_against_baseline_returns_one(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main([*ARGS, "--accept"]) == 0
    use(monkeypatch, FakeEvaluator([answers(syn_chat_en=res("no"))]))
    assert quality_eval.main(ARGS) == 1
    assert "к лучшему прогону" in capsys.readouterr().out


def test_checklist_option_accepts_state_export(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main(["--checklist", str(ROOT / "tests/fixtures/state_prototype.json")]) == 0
    assert fake.calls


def test_make_eval_runs_quality_eval_live_with_args() -> None:
    out = subprocess.run(
        ["make", "-n", "eval", "ARGS=--accept"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert "CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval --accept" in out


def test_eval_reports_are_ignored_by_git() -> None:
    out = subprocess.run(
        ["git", "check-ignore", "-q", "eval/reports/20261107T000000Z.json"], cwd=ROOT, check=False
    )
    assert out.returncode == 0


# --- отложенные критерии -----------------------------------------------------------------------

HOLDOUT_TEXT = "Секретный текст отложенного критерия."


def holdout_criteria(*replaces: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"h{i}",
            "sec": 0,
            "name": f"Отложенный {i}",
            "type": "bool",
            "w": 10,
            "na": False,
            "text": f"{HOLDOUT_TEXT} {i}",
            "replaces": cid,
        }
        for i, cid in enumerate(replaces, start=1)
    ]


def write_holdout(root: Path, criteria: list[dict[str, Any]], labels: list[dict[str, Any]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "criteria.json").write_text(json.dumps(criteria, ensure_ascii=False), encoding="utf-8")
    (root / "labels.jsonl").write_text("\n".join(json.dumps(r) for r in labels) + "\n", encoding="utf-8")
    return root


def hl(dlg: str, cid: str, *ok: Any) -> dict[str, Any]:
    return {"dlg": dlg, "cid": cid, "ok": list(ok), "by": "team", "note": ""}


def test_holdout_without_dir_returns_two_without_calls(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CQA_HOLDOUT_DIR", raising=False)
    fake = use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main([*ARGS, "--holdout"]) == 2
    assert "вне репозитория" in capsys.readouterr().out
    assert fake.calls == []


def test_holdout_dir_inside_repository_returns_two_without_calls(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CQA_HOLDOUT_DIR", str(ROOT / "eval"))
    fake = use(monkeypatch, FakeEvaluator([answers()]))
    assert quality_eval.main([*ARGS, "--holdout"]) == 2
    assert "вне репозитория" in capsys.readouterr().out
    assert fake.calls == []


def test_load_holdout_requires_replaces_of_known_criterion(tmp_path: Path) -> None:
    good = holdout_criteria("01")
    write_holdout(tmp_path, [{k: v for k, v in good[0].items() if k != "replaces"}], [])
    with pytest.raises(ValueError, match="replaces"):
        load_holdout(tmp_path, CHECKLIST)
    write_holdout(tmp_path, holdout_criteria("99"), [])
    with pytest.raises(ValueError, match="99"):
        load_holdout(tmp_path, CHECKLIST)
    write_holdout(tmp_path, [good[0] | {"type": "dice"}], [])
    with pytest.raises(ValueError):
        load_holdout(tmp_path, CHECKLIST)


def test_load_holdout_checks_labels_against_replacing_criterion(tmp_path: Path) -> None:
    write_holdout(
        tmp_path,
        holdout_criteria("01", "04"),
        [hl("syn-chat-ru", "h1", "yes"), hl("syn-chat-ru", "h2", "no")],
    )
    criteria, labels = load_holdout(tmp_path, CHECKLIST)
    assert [(c.id, replaces) for c, replaces in criteria] == [("h1", "01"), ("h2", "04")]
    assert [(g.dlg, g.cid, g.ok) for g in labels] == [
        ("syn-chat-ru", "h1", ("yes",)),
        ("syn-chat-ru", "h2", ("no",)),
    ]
    write_holdout(tmp_path, holdout_criteria("01"), [hl("syn-chat-ru", "h1", 15)])
    with pytest.raises(ValueError, match="строка 1"):
        load_holdout(tmp_path, CHECKLIST)
