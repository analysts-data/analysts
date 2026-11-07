from typing import Any

import pytest

from cqa.adapters.store import Store
from cqa.domain.models import Appeal, Cost, CriterionResult, Dialog, Mode
from cqa.domain.review import fingerprint
from cqa.services.state import build_state, mode_from_settings
from cqa.settings import Settings
from fakes import prototype_checklist

MODE = Mode(where="kz", anonymized=True, model="qwen3-6", verifier=None)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CQA_DATA_WHERE", "CQA_ANONYMIZE", "CQA_LLM_MODEL", "CQA_VERIFIER"):
        monkeypatch.delenv(name, raising=False)


def evaluate_all(store: Store, dialog: Dialog) -> None:
    cl = prototype_checklist()
    for c in cl.criteria:
        store.add_result(dialog.id, c.id, cl.version, fingerprint(cl, c), dialog.res[c.id])


def file(store: Store, *, status: str, fp: str, kind: str = "appeal") -> Appeal:
    body: dict[str, Any] = {
        "id": "", "kind": kind, "dlg": "call-024", "cid": "04", "from": 15, "to": None, "ev": [],
        "by": "Оператор", "at": "07.11 15:10", "status": status, "comment": "Срок назвать было нельзя.",
    }  # fmt: skip
    if kind == "appeal":
        body["ask"] = 20
    return store.add_appeal(Appeal.model_validate(body), fp)


def dialog_of(state: dict[str, Any], dialog_id: str) -> dict[str, Any]:
    return next(d for d in state["dialogs"] if d["id"] == dialog_id)


def test_state_has_exactly_six_keys_and_seed_version(store: Store) -> None:
    state = build_state(store, MODE)
    assert set(state) == {"checklist", "versions", "dialogs", "appeals", "owners", "mode"}
    assert state["versions"] == [{"v": 3, "note": "начальная версия"}]
    assert state["checklist"]["version"] == 3
    assert state["mode"] == MODE.model_dump(mode="json")


def test_evaluated_dialog_has_all_current_results(store: Store, dialogs: list[Dialog]) -> None:
    evaluate_all(store, dialogs[0])
    state = build_state(store, MODE)
    call = dialog_of(state, "call-024")
    assert sorted(call["res"]) == ["01", "02", "03", "04", "05", "06", "07", "08"]
    assert call["res"]["04"]["a"] == 15
    assert dialog_of(state, "p1-ru-003")["res"] == {}


def test_result_with_foreign_fingerprint_is_not_current(store: Store) -> None:
    store.add_result("call-024", "04", 2, "0123456789abcdef", CriterionResult(a=15))
    assert dialog_of(build_state(store, MODE), "call-024")["res"] == {}


def test_result_without_second_opinion_has_no_alt_key(store: Store, dialogs: list[Dialog]) -> None:
    evaluate_all(store, dialogs[0])
    result = dialog_of(build_state(store, MODE), "call-024")["res"]["01"]
    assert "alt" not in result
    assert "pending" not in result


def test_lines_keep_who(store: Store) -> None:
    assert "who" in dialog_of(build_state(store, MODE), "call-024")["lines"][0]


def test_open_appeals_stay_and_decided_ones_follow_the_fingerprint(store: Store) -> None:
    file(store, status="pending", fp="old")
    file(store, status="closed", fp="old")
    file(store, status="changed", fp="old")
    cl = prototype_checklist()
    current = fingerprint(cl, cl.criteria[3])
    file(store, status="confirmed", fp=current)
    assert [a["status"] for a in build_state(store, MODE)["appeals"]] == ["pending", "closed", "confirmed"]


def test_review_record_has_no_ask_and_appeal_keeps_from_key(store: Store) -> None:
    file(store, status="pending", fp="x")
    file(store, status="closed", fp="x", kind="review")
    appeal, review = build_state(store, MODE)["appeals"]
    assert appeal["from"] == 15 and appeal["ask"] == 20 and appeal["to"] is None
    assert "ask" not in review


def test_owners_come_from_the_table(store: Store) -> None:
    store.set_owners({"Не назван срок ответа": "Инструкция"})
    assert build_state(store, MODE)["owners"] == {"Не назван срок ответа": "Инструкция"}


def test_state_has_no_total_and_no_audio_url(store: Store, dialogs: list[Dialog]) -> None:
    evaluate_all(store, dialogs[0])
    for dialog in build_state(store, MODE)["dialogs"]:
        assert not {"total", "score", "W", "audio_url"} & set(dialog)


def test_cost_only_on_evaluated_dialog(store: Store) -> None:
    store.set_cost("call-024", Cost(calls=8, verifier_calls=1, usd=0.0082, ms=41000))
    state = build_state(store, MODE)
    assert dialog_of(state, "call-024")["cost"] == {
        "calls": 8,
        "verifier_calls": 1,
        "usd": 0.0082,
        "ms": 41000,
    }
    assert "cost" not in dialog_of(state, "p1-ru-003")


def test_mode_defaults_to_scenario_4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_VERIFIER", "")
    mode = mode_from_settings(Settings(_env_file=None))
    assert mode.model_dump(mode="json") == {
        "where": "kz",
        "anonymized": True,
        "model": "qwen3-6",
        "verifier": None,
    }


def test_mode_follows_fallback_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_DATA_WHERE", "external")
    monkeypatch.setenv("CQA_VERIFIER", "jev")
    mode = mode_from_settings(Settings(_env_file=None))
    assert (mode.where, mode.verifier) == ("external", "jev")
