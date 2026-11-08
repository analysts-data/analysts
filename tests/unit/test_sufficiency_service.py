"""Достаточность данных в состоянии, запусках, проверке, отчёте и файле результатов; диалоги синтетические."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Criterion, CriterionResult, Dialog, Mode
from cqa.domain.results import to_results
from cqa.domain.review import ASTANA, awaits_review, fingerprint
from cqa.domain.sufficiency import UNSUPPORTED
from cqa.services.appeals import record_review
from cqa.services.runs import Runner
from cqa.services.state import build_state, current_state, report
from fakes import FakeEvaluator, prototype_checklist

CHECKLIST = prototype_checklist()
MODE = Mode(where="local", anonymized=True, model="m", verifier=None)
ROOT = Path(__file__).resolve().parents[2]
CODES: dict[str, str] = json.loads((ROOT / "results" / "criteria_map.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 8, tzinfo=ASTANA)


def synthetic(dialog_id: str, lines: list[tuple[str, str]], ch: str = "chat") -> Dialog:
    return Dialog.model_validate(
        {
            "id": dialog_id,
            "ch": ch,
            "lang": "RU",
            "at": "08.11 09:00",
            "lines": [
                {"n": i, "t": float(i) if ch == "call" else f"00:{i:02d}", "who": w, "text": t, "seg": "conv"}
                for i, (w, t) in enumerate(lines, 1)
            ],
        }
    )


NO_OPERATOR = synthetic("syn-noop", [("client", "Где мой перевод?"), ("client", "Алло?")])
SHORT = synthetic("syn-short", [("operator", "Здравствуйте, чем помочь?"), ("client", "Уже ничем")])


@pytest.fixture
def full(store: Store) -> Store:
    store.add_dialogs([NO_OPERATOR, SHORT], {})
    return store


def _state(store: Store) -> dict[str, dict]:
    return {d["id"]: d for d in build_state(store, MODE)["dialogs"]}


def _answer(store: Store, dialog: Dialog, cid: str, result: CriterionResult) -> None:
    c = next(c for c in CHECKLIST.criteria if c.id == cid)
    store.add_result(dialog.id, cid, CHECKLIST.version, fingerprint(CHECKLIST, c, dialog.ch), result)


def _evaluated(store: Store, dialog: Dialog) -> None:
    """Каждый критерий с основанием: худший ответ, флаг без нарушений."""

    def worst(c: Criterion) -> CriterionResult:
        a = {q.k: False for q in c.questions or []} if c.type == "flag" else "no" if c.type == "bool" else 0
        return CriterionResult(a=a, ev=[1], why="есть", model="m")

    for c in CHECKLIST.criteria:
        _answer(store, dialog, c.id, worst(c))


def test_normal_dialogs_stay_ok_and_insufficient_ones_carry_reasons(full: Store) -> None:
    dialogs = _state(full)
    assert {i: dialogs[i]["sufficiency"]["status"] for i in dialogs} == {
        "call-024": "ok", "p1-ru-003": "ok", "syn-noop": "block", "syn-short": "flag",
    }  # fmt: skip
    assert dialogs["syn-noop"]["sufficiency"]["reasons"] == [
        {
            "id": "no_operator",
            "text": "Нет реплик оператора",
            "basis": "реплик клиента — 2, реплик оператора нет",
            "outcome": "block",
        }
    ]


def test_answer_without_basis_on_flagged_dialog_needs_review_and_can_be_decided(full: Store) -> None:
    _answer(full, SHORT, "01", CriterionResult(a="yes", model="m"))
    _answer(full, SHORT, "05", CriterionResult(a="no", ev=[1], model="m"))
    res = _state(full)["syn-short"]["res"]
    assert (res["01"]["a"], res["01"]["reviewWhy"], "reviewWhy" in res["05"]) == ("yes", UNSUPPORTED, False)
    checklist, dialogs, _ = current_state(full)
    assert awaits_review(checklist.criteria, next(d for d in dialogs if d.id == "syn-short"), set())
    record = record_review(
        full, dlg="syn-short", cid="01", frm="yes", to="no", reason="Приветствия нет", reviewer="КК", now=NOW
    )
    assert (record.kind, record.status) == ("review", "changed")


async def test_run_skips_blocked_dialogs_and_counts_them(full: Store) -> None:
    evaluator = FakeEvaluator()
    runner = Runner(full, evaluator, parallel=1)
    run_id = runner.start(["syn-noop", "syn-short"], None)
    while runner.progress(run_id)["status"] == "running":
        await asyncio.sleep(0.01)
    assert (runner.progress(run_id)["insufficient"], evaluator.order) == (1, ["syn-short"])


def test_blocked_dialog_is_out_of_averages_and_an_error_in_results(full: Store) -> None:
    _evaluated(full, NO_OPERATOR)  # оценён до смены правил: итог по нему всё равно не выдумываем
    _evaluated(full, next(d for d in current_state(full)[1] if d.id == "p1-ru-003"))
    rep = report(full, "json", lang=None, ch=None, now=NOW)
    assert isinstance(rep, dict)
    assert (rep["summary"]["scored"], rep["summary"]["insufficient"]) == (1, 1)
    checklist, dialogs, appeals = current_state(full)
    doc = to_results(
        ["syn-noop"], {d.id: d for d in dialogs}, checklist, appeals, CODES, team="t", model={"name": "m"}
    )
    assert doc["results"] == [
        {
            "conversation_id": "syn-noop",
            "status": "error",
            "criteria": [],
            "score": None,
            "error": "недостаточно данных: Нет реплик оператора (реплик клиента — 2, реплик оператора нет)",
        }
    ]
