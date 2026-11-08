"""Маркеры диалогов и правила алертов: каждое срабатывание с обоснованием `basis` (domain/alerts.py)."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cqa.domain.alerts import (
    DEFAULT_RULES,
    AlertRule,
    DialogView,
    check_alerts,
    check_rules,
    dialog_view,
)
from cqa.domain.models import Appeal, Checklist, Dialog
from cqa.domain.review import ASTANA, effective_answer
from cqa.domain.scoring import total

STATE = json.loads((Path(__file__).parents[1] / "fixtures" / "analytics_state.json").read_text("utf-8"))
CHECKLIST = Checklist.model_validate(STATE["checklist"])
DIALOGS = {d["id"]: Dialog.model_validate(d) for d in STATE["dialogs"]}
APPEALS = [Appeal.model_validate(a) for a in STATE["appeals"]]
NOW = datetime(2026, 11, 8, 16, 0, tzinfo=ASTANA)
CATALOG = ["Жалоба", "Эскалация"]


def rule(kind: str, **params: Any) -> AlertRule:
    return AlertRule(id=f"r-{kind}", title="Правило", kind=kind, params=params, severity="warning", why="w")


def view(
    dialog_id: str,
    *,
    appeals: list[Appeal] = APPEALS,
    prosody: dict[str, Any] | None = None,
    manual: list[dict[str, str]] | None = None,
    low: AlertRule | None = None,
) -> DialogView:
    return dialog_view(CHECKLIST, DIALOGS[dialog_id], appeals, prosody=prosody, manual=manual or [], low=low)


def marker(v: DialogView, k: str) -> dict[str, Any] | None:
    return next((m for m in v.markers if m["k"] == k), None)


def views(**kw: Any) -> list[DialogView]:
    return [view(i, **kw) for i in DIALOGS]


# --- автоматические маркеры ---


def test_gross_marker_cites_flag_question_lines_and_model_as_source() -> None:
    m = marker(view("p1-ru-022"), "gross")

    assert m is not None and m["auto"] is True and m["label"] == "Грубое нарушение"
    assert m["basis"]["criteria"] == ["08"]
    assert m["basis"]["flags"] == ["paid"]
    assert m["basis"]["lines"] == [6]
    assert m["basis"]["appeals"] == []
    assert m["basis"]["why"].startswith("Почему: ")
    assert "Платная услуга в обход компании" in m["basis"]["why"]
    assert "зафиксировано моделью, решением не отменено" in m["basis"]["why"]


def test_gross_marker_follows_decision_that_cleared_or_set_the_flag() -> None:
    clear = Appeal.model_validate(
        {"id": "a9", "kind": "review", "dlg": "p1-ru-022", "cid": "08", "from": {"paid": True},
         "to": {"insult": False, "paid": False, "leak": False}, "by": "КК", "at": "08.11 10:00",
         "status": "changed"}
    )  # fmt: skip
    set_ = clear.model_copy(update={"dlg": "p1-en-006", "to": {"insult": True, "paid": False, "leak": False}})

    assert marker(view("p1-ru-022", appeals=[clear]), "gross") is None
    m = marker(view("p1-en-006", appeals=[set_]), "gross")
    assert m is not None and m["basis"]["appeals"] == ["a9"]
    assert "подтверждено решением a9" in m["basis"]["why"]


def test_no_next_step_marker_names_answer_and_top_step_and_skips_raised_by_decision() -> None:
    m = marker(view("call-024"), "no_next_step")

    assert m is not None and m["label"] == "Нет следующего шага"
    assert m["basis"]["criteria"] == ["04"]
    assert m["basis"]["answers"] == {"04": 15}
    assert m["basis"]["top"] == {"04": 20}
    assert m["basis"]["lines"] == [9, 10]
    assert marker(view("p1-en-006"), "no_next_step") is None  # a3 поднял до 20
    assert marker(view("p1-ru-025"), "no_next_step") is None  # N/A — не потеря


def test_needs_review_marker_for_disagreement_and_failed_evidence_without_decision() -> None:
    disagree = marker(view("p1-en-008"), "needs_review")
    failed = marker(view("p1-kz-003"), "needs_review")

    assert disagree is not None and disagree["basis"]["criteria"] == ["07"]
    assert "модели расходятся" in disagree["basis"]["why"]
    assert failed is not None and failed["basis"]["criteria"] == ["06"]
    assert "основание не найдено" in failed["basis"]["why"]
    assert marker(view("call-024"), "needs_review") is None  # r1 решил расхождение
    assert marker(view("p1-ru-029"), "needs_review") is None  # отмечен проверенным


def test_appeal_marker_lists_pending_appeals_only() -> None:
    m = marker(view("call-024"), "appeal")

    assert m is not None and m["basis"]["appeals"] == ["a1"] and m["basis"]["criteria"] == ["04"]
    assert "07.11 15:10" in m["basis"]["why"]
    assert marker(view("p1-ru-003"), "appeal") is None  # a2 закрыта


def test_prosody_markers_come_from_cached_flags_with_client_lines_only() -> None:
    lines = DIALOGS["call-024"].lines or []
    client = next(ln.n for ln in lines if getattr(ln, "who", "") == "client")
    operator = next(ln.n for ln in lines if getattr(ln, "who", "") == "operator")
    prosody = {
        "lines": [
            {"n": client, "flags": ["raised"], "pause": None},
            {"n": operator, "flags": ["raised", "long_pause"], "pause": 9.2},
        ]
    }

    v = view("call-024", prosody=prosody)
    raised, pause = marker(v, "raised_tone"), marker(v, "long_pause")

    assert raised is not None and raised["label"] == "Клиент повысил тон"
    assert raised["basis"]["lines"] == [client]
    assert "3 полутона" in raised["basis"]["why"]
    assert pause is not None and pause["basis"]["lines"] == [operator]
    assert pause["basis"]["value"] == 9.2 and pause["basis"]["threshold"] == 5.0
    assert marker(view("call-024"), "raised_tone") is None  # интонация не считалась — маркера нет


def test_low_total_marker_uses_enabled_low_total_rule_threshold() -> None:
    d = DIALOGS["call-024"]
    mine = [a for a in APPEALS if a.dlg == d.id]
    expected = total(
        CHECKLIST, {c: effective_answer(r, [a for a in mine if a.cid == c]) for c, r in d.res.items()}
    )
    low = rule("low_total", threshold=101)

    m = marker(view("call-024", low=low), "low_total")

    assert m is not None and m["basis"] == {
        "rule": "r-low_total",
        "threshold": 101,
        "value": expected,
        "why": m["basis"]["why"],
    }
    assert marker(view("call-024", low=rule("low_total", threshold=0)), "low_total") is None
    assert marker(view("call-024"), "low_total") is None


def test_manual_markers_follow_auto_ones() -> None:
    v = view("call-024", manual=[{"label": "Жалоба", "by": "Анна", "at": "08.11 10:00"}])

    assert v.markers[-1] == {
        "k": "Жалоба",
        "label": "Жалоба",
        "auto": False,
        "by": "Анна",
        "at": "08.11 10:00",
    }
    assert all(m["auto"] for m in v.markers[:-1])


# --- правила алертов ---


def fired(
    r: AlertRule, vs: list[DialogView], runs: list[tuple[int, str, list[str]]] | None = None
) -> list[Any]:
    return check_alerts([r], vs, APPEALS, runs or [], NOW)


def test_gross_error_rule_fires_once_per_dialog_with_marker_basis() -> None:
    hits = fired(rule("gross_error"), views())

    assert sorted(h["target_id"] for h in hits) == ["p1-kz-015", "p1-ru-009", "p1-ru-022", "p1-ru-029"]
    h = next(h for h in hits if h["target_id"] == "p1-ru-022")
    assert h["rule_id"] == "r-gross_error" and h["severity"] == "warning" and h["target_type"] == "dialog"
    assert h["basis"]["rule"] == "r-gross_error" and h["basis"]["lines"] == [6]
    assert h["basis"]["dialogs"] == ["p1-ru-022"]


def test_low_total_rule_reports_value_and_threshold() -> None:
    hits = fired(rule("low_total", threshold=101), views())

    assert {h["target_id"] for h in hits} == {v.id for v in views() if v.total is not None}
    assert all(h["basis"]["threshold"] == 101 and h["basis"]["value"] < 101 for h in hits)
    assert fired(rule("low_total", threshold=0), views()) == []


def test_operator_avg_uses_last_n_scored_dialogs_and_skips_unknown_operator() -> None:
    vs = [
        DialogView("d1", "Анна", 100.0, []),
        DialogView("d2", "Анна", 50.0, []),
        DialogView("d3", "Анна", 60.0, []),
        DialogView("d4", "Анна", None, []),
        DialogView("d5", "Борис", 10.0, []),
        DialogView("d6", None, 10.0, []),
    ]

    hits = fired(rule("operator_avg", n=2, threshold=70, min_dialogs=2), vs)

    assert [(h["target_type"], h["target_id"]) for h in hits] == [("operator", "Анна")]
    assert hits[0]["basis"]["value"] == 55.0 and hits[0]["basis"]["dialogs"] == ["d2", "d3"]


def test_no_next_step_share_fires_above_threshold_with_enough_dialogs() -> None:
    nx = {"k": "no_next_step", "label": "Нет следующего шага", "auto": True, "basis": {}}
    vs = [DialogView(f"d{i}", None, 50.0, [nx] if i < 2 else []) for i in range(5)]

    hits = fired(rule("no_next_step_share", threshold=30, min_dialogs=5), vs)

    assert [(h["target_type"], h["target_id"]) for h in hits] == [("set", "all")]
    assert hits[0]["basis"]["value"] == 40.0 and hits[0]["basis"]["dialogs"] == ["d0", "d1"]
    assert fired(rule("no_next_step_share", threshold=40, min_dialogs=5), vs) == []
    assert fired(rule("no_next_step_share", threshold=30, min_dialogs=6), vs) == []


def test_raised_tone_rule_follows_prosody_marker() -> None:
    lines = DIALOGS["call-024"].lines or []
    client = next(ln.n for ln in lines if getattr(ln, "who", "") == "client")
    vs = [view("call-024", prosody={"lines": [{"n": client, "flags": ["raised"]}]}), view("p1-ru-003")]

    assert [h["target_id"] for h in fired(rule("raised_tone"), vs)] == ["call-024"]


def test_appeal_overdue_counts_hours_since_filing() -> None:
    hits = fired(rule("appeal_overdue", hours=24), views())

    assert [(h["target_type"], h["target_id"]) for h in hits] == [("appeal", "a1")]
    assert hits[0]["basis"]["value"] == pytest.approx(24.8, abs=0.1)
    assert hits[0]["basis"]["dialogs"] == ["call-024"] and hits[0]["basis"]["criteria"] == ["04"]
    assert fired(rule("appeal_overdue", hours=25), views()) == []


def test_run_errors_rule_fires_for_finished_run_with_errors_without_error_text() -> None:
    runs = [(1, "done", ["call-024: boom secret"]), (2, "done", []), (3, "running", ["x: y"])]

    hits = fired(rule("run_errors"), [], runs)

    assert [(h["target_type"], h["target_id"]) for h in hits] == [("run", "1")]
    assert hits[0]["basis"]["dialogs"] == ["call-024"] and hits[0]["basis"]["value"] == 1
    assert "boom" not in json.dumps(hits, ensure_ascii=False)


def test_marker_rule_fires_on_manual_label() -> None:
    vs = [
        view("call-024", manual=[{"label": "Жалоба", "by": "Анна", "at": "08.11 10:00"}]),
        view("p1-ru-003"),
    ]

    hits = fired(rule("marker", label="Жалоба"), vs)

    assert [h["target_id"] for h in hits] == ["call-024"]
    assert "Анна" in hits[0]["basis"]["why"]


def test_disabled_rule_does_not_fire() -> None:
    assert fired(rule("gross_error").model_copy(update={"enabled": False}), views()) == []


def test_titles_and_basis_carry_no_dialogue_text() -> None:
    lines = DIALOGS["call-024"].lines or []
    texts = [ln.text for ln in lines if getattr(ln, "text", "")]
    vs = views(manual=[{"label": "Жалоба", "by": "Анна", "at": "08.11 10:00"}])

    dump = json.dumps(check_alerts(DEFAULT_RULES, vs, APPEALS, [], NOW), ensure_ascii=False)

    assert not [t for t in texts if len(t) > 15 and t in dump]


# --- проверка правил ---


def test_default_rules_pass_their_own_check() -> None:
    rules, errors = check_rules([r.model_dump() for r in DEFAULT_RULES], ["Жалоба"])

    assert errors == [] and rules == DEFAULT_RULES
    assert all(r.why for r in DEFAULT_RULES)


def test_check_rules_fills_missing_params_with_defaults() -> None:
    rules, errors = check_rules(
        [{"id": "x", "title": "Низкий итог", "kind": "low_total", "severity": "info", "why": "норматив"}], []
    )

    assert errors == [] and rules[0].params == {"threshold": 60}


def test_check_rules_reports_every_bad_field_in_russian() -> None:
    raw = [
        {"id": "a", "title": "A", "kind": "low_total", "severity": "loud", "params": {"threshold": 150}},
        {"id": "a", "title": "", "kind": "nope", "severity": "info"},
        {"id": "c", "title": "C", "kind": "marker", "severity": "info", "params": {"label": "Нет такого"}},
        {"id": "d", "title": "D", "kind": "operator_avg", "severity": "info", "why": "w",
         "params": {"n": 2.5, "extra": 1}},
    ]  # fmt: skip

    rules, errors = check_rules(raw, CATALOG)

    assert rules == []
    locs = {tuple(e["loc"]): e["msg"] for e in errors}
    assert set(locs) == {
        ("body", 0, "severity"),
        ("body", 0, "params", "threshold"),
        ("body", 0, "why"),
        ("body", 1, "id"),
        ("body", 1, "title"),
        ("body", 1, "kind"),
        ("body", 2, "params", "label"),
        ("body", 3, "params", "n"),
        ("body", 3, "params", "extra"),
    }
    assert "от 0 до 100" in locs[("body", 0, "params", "threshold")]
    assert "повторяется" in locs[("body", 1, "id")]
    assert "целое" in locs[("body", 3, "params", "n")]
    assert "Нет такого" in locs[("body", 2, "params", "label")]


def test_check_rules_rejects_non_list() -> None:
    assert check_rules({"id": "x"}, [])[1] == [{"loc": ["body"], "msg": "Нужен список правил"}]
