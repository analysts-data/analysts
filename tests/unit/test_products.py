"""Темы обращений: справочник как данные, ответ модели и Jev с обоснованием, кэш, аналитика по темам."""

import json
from typing import Any

from cqa.domain.models import Appeal, Checklist, Dialog, Product, ProductTag, RiskKind, RiskMark
from cqa.domain.products import (
    PRODUCT_SURE,
    jev_risks,
    jev_tag,
    model_risks,
    model_tag,
    product_key,
    product_messages,
)
from cqa.domain.prompt import build_messages, render_dialog
from cqa.domain.report import build_report, product_stats, to_html, to_markdown
from fakes import FIXTURES, prototype_checklist, prototype_dialogs

PRODUCTS = [Product.model_validate(p) for p in json.loads((FIXTURES / "products.json").read_text("utf-8"))]
NAMES = {p.id: p.name for p in PRODUCTS}
LINES = {1, 2, 3, 4, 5}


def test_seed_taxonomy_is_the_contact_centre_topic_list() -> None:
    assert [p.name for p in PRODUCTS] == [
        "Брокерский счёт и открытие",
        "Пополнение и вывод средств",
        "Торговая платформа и заявки",
        "Тарифы и комиссии",
        "Верификация, KYC и документы",
        "Налоги и справки",
        "IPO и подписки",
        "Технические проблемы приложения",
        "Прочее",
    ]


def test_prompt_lists_every_topic_code_and_puts_the_dialog_inside_tags() -> None:
    system, user = product_messages("[1 · 00:01] client: Где мои деньги?", PRODUCTS)
    assert system["role"] == "system" and "JSON" in system["content"]
    for p in PRODUCTS:
        assert f"- {p.id} — {p.name}: {p.description}" in user["content"]
    assert "<dialog>\n[1 · 00:01] client: Где мои деньги?\n</dialog>" in user["content"]


def test_model_answer_becomes_topic_with_reason_and_existing_line_numbers() -> None:
    reply = '{"reason_ru": "Клиент ждёт вывод (реплики 3, 4)", "turn_ids": [3, 4, 99], "answer": "funding"}'
    tag = model_tag(reply, PRODUCTS, LINES, by="qwen3-6", cost=0.0004)
    assert tag == ProductTag(
        status="done",
        id="funding",
        name=NAMES["funding"],
        confidence=None,
        by="qwen3-6",
        basis={"why": "Клиент ждёт вывод (реплики 3, 4)", "ev": [3, 4]},
        cost=0.0004,
    )


def test_model_answer_without_existing_lines_goes_to_review() -> None:
    tag = model_tag(
        '{"reason_ru": "Похоже на вывод", "turn_ids": [], "answer": "funding"}', PRODUCTS, LINES, by="m"
    )
    assert (tag.status, tag.needs_review, tag.basis.ev) == ("done", True, [])


def test_model_answer_outside_the_taxonomy_is_an_error_with_text() -> None:
    tag = model_tag(
        '{"reason_ru": "…", "turn_ids": [1], "answer": "loans"}', PRODUCTS, LINES, by="m", cost=0.1
    )
    assert (tag.status, tag.id, tag.error, tag.cost) == (
        "error",
        None,
        "модель вернула тему не из справочника: loans",
        0.1,
    )
    assert model_tag("не JSON", PRODUCTS, LINES, by="m").error == "нет объекта JSON с полем answer"


def test_jev_answer_keeps_probability_of_every_topic_and_the_threshold_with_its_reason() -> None:
    probs = {"funding": 0.91, "account": 0.05, "nope": 0.04}
    tag = jev_tag("funding", probs, 0.91, PRODUCTS, cost=0.00006)
    assert (tag.status, tag.id, tag.name, tag.confidence, tag.by, tag.needs_review) == (
        "done",
        "funding",
        NAMES["funding"],
        0.91,
        "jev",
        False,
    )
    assert tag.basis.probs == {"funding": 0.91, "account": 0.05}
    assert tag.basis.threshold == PRODUCT_SURE
    assert tag.basis.threshold_why and "0,6" in tag.basis.threshold_why
    assert tag.basis.why == f"Jev выбрал «{NAMES['funding']}» с вероятностью 0,91"


def test_jev_answer_below_threshold_or_without_probability_needs_review() -> None:
    low = jev_tag("funding", {"funding": 0.4, "account": 0.35}, 0.4, PRODUCTS, cost=0.0)
    assert low.needs_review and low.basis.why and "ниже порога 0,6" in low.basis.why
    assert jev_tag("funding", {}, None, PRODUCTS, cost=0.0).needs_review
    assert jev_tag(None, {}, None, PRODUCTS, cost=0.0).status == "error"


def test_cache_key_depends_on_taxonomy_and_dialog_text_only() -> None:
    d = prototype_dialogs()[0]
    key = product_key(PRODUCTS, d)
    assert product_key(PRODUCTS, d.model_copy(update={"reviewed": True, "title": "x"})) == key
    renamed = [PRODUCTS[0].model_copy(update={"name": "Счёт"}), *PRODUCTS[1:]]
    assert product_key(renamed, d) != key
    other = prototype_dialogs()[1]
    assert product_key(PRODUCTS, other) != key


def test_topic_on_a_dialog_does_not_change_scoring_requests() -> None:
    d = next(x for x in prototype_dialogs() if x.lines)
    tagged = d.model_copy(update={"product": jev_tag("funding", {"funding": 1.0}, 1.0, PRODUCTS, cost=0)})
    checklist = prototype_checklist()
    for c in checklist.criteria:
        assert build_messages(render_dialog(tagged), checklist.rules, c, d.ch) == build_messages(
            render_dialog(d), checklist.rules, c, d.ch
        )


# --- аналитика по темам на фикстуре аналитики ---


def _state(tags: dict[str, str]) -> tuple[Checklist, list[Dialog], list[Appeal], dict[str, str]]:
    s: dict[str, Any] = json.loads((FIXTURES / "analytics_state.json").read_text(encoding="utf-8"))
    dialogs = [Dialog.model_validate(d) for d in s["dialogs"]]
    dialogs = [
        d.model_copy(update={"product": jev_tag(tags[d.id], {}, 0.9, PRODUCTS, cost=0)})
        if d.id in tags
        else d
        for d in dialogs
    ]
    return (
        Checklist.model_validate(s["checklist"]),
        dialogs,
        [Appeal.model_validate(a) for a in s["appeals"]],
        s["owners"],
    )


def _split() -> dict[str, str]:
    s = json.loads((FIXTURES / "analytics_state.json").read_text(encoding="utf-8"))
    ids = [d["id"] for d in s["dialogs"]]
    return {i: "funding" for i in ids[:6]} | {i: "trading" for i in ids[6:9]}  # последний без темы


def test_stats_per_topic_match_the_report_on_the_same_dialogs() -> None:
    checklist, dialogs, appeals, owners = _state(_split())
    stats = {s["id"]: s for s in product_stats(checklist, dialogs, appeals, owners, PRODUCTS)}
    assert list(stats) == [p.id for p in PRODUCTS] + [None]
    for pid, ids in (("funding", 6), ("trading", 3), (None, 1)):
        subset = [d for d in dialogs if (d.product.id if d.product else None) == pid]
        rep = build_report(checklist, subset, appeals, owners, at="")
        s = stats[pid]
        assert s["dialogs"] == ids == len(subset)
        assert s["avg_total"] == rep["summary"]["avg_total"]
        assert s["risk_share"] == rep["summary"]["risk"]["share"]
        assert s["no_next_step_share"] == rep["summary"]["no_next_step"]["share"]
        assert s["reasons"] == [
            {"tag": r["tag"], "dialogs": r["dialogs"], "owner": r["owner"]} for r in rep["reasons"][:3]
        ]
        assert s["weakest"] == [
            {"id": c["id"], "name": c["name"], "share": c["share"]}
            for c in rep["criteria"][:3]
            if c["share"] < 1
        ]
    assert stats[None]["name"] == "Тема не определена"
    assert (stats["tax"]["dialogs"], stats["tax"]["avg_total"], stats["tax"]["reasons"]) == (0, None, [])


def test_stats_count_dialogs_whose_topic_needs_review() -> None:
    checklist, dialogs, appeals, owners = _state({})
    mark = RiskMark(k="churn", label="Угроза ухода", lines=[1], basis="…")
    first = dialogs[0].model_copy(
        update={"product": jev_tag("ipo", {"ipo": 0.3}, 0.3, PRODUCTS, cost=0), "risks": [mark, mark]}
    )
    stats = {s["id"]: s for s in product_stats(checklist, [first], appeals, owners, PRODUCTS)}
    assert (stats["ipo"]["dialogs"], stats["ipo"]["needs_review"]) == (1, 1)
    assert stats["ipo"]["risks"] == [{"k": "churn", "label": "Угроза ухода", "dialogs": 1}]


def test_report_has_a_by_topic_section_in_json_markdown_and_html() -> None:
    checklist, dialogs, appeals, owners = _state(_split())
    rep = build_report(checklist, dialogs, appeals, owners, at="08.11 07:00", products=PRODUCTS)
    assert [p["id"] for p in rep["products"]] == ["funding", "trading", None]
    md = to_markdown(rep)
    assert "## По продуктам" in md and f"| {NAMES['funding']} | 6 |" in md
    assert "<h2>По продуктам</h2>" in to_html(rep)
    assert "products" not in build_report(checklist, dialogs, appeals, owners, at="")


# --- маркеры риска в том же запросе ---

RISKS = [RiskKind.model_validate(r) for r in json.loads((FIXTURES / "risks.json").read_text("utf-8"))]
LABELS = {r.k: r.label for r in RISKS}


def test_prompt_lists_risk_markers_with_codes() -> None:
    _, user = product_messages("[1 · 00:01] client: Закрою счёт!", PRODUCTS, RISKS)
    for r in RISKS:
        assert f"- {r.k}: {r.text}" in user["content"]


def test_model_risks_carry_lines_and_the_model_reason_unknown_codes_dropped() -> None:
    reply = json.dumps(
        {
            "reason_ru": "…",
            "turn_ids": [1],
            "answer": "funding",
            "risks": [
                {"k": "churn", "turn_ids": [3, 99], "reason_ru": "Грозит закрыть счёт (реплика 3)"},
                {"k": "nope", "turn_ids": [1], "reason_ru": "x"},
                {"k": "callback", "turn_ids": "1", "reason_ru": None},
            ],
        },
        ensure_ascii=False,
    )
    assert model_risks(reply, RISKS, LINES) == [
        RiskMark(k="churn", label=LABELS["churn"], lines=[3], basis="Грозит закрыть счёт (реплика 3)"),
        RiskMark(k="callback", label=LABELS["callback"], lines=[], basis="модель не указала причину"),
    ]
    assert model_risks("не JSON", RISKS, LINES) == []


def test_jev_risks_above_half_with_probability_as_basis() -> None:
    marks = jev_risks({"churn": 0.82, "manager": 0.2, "nope": 0.9}, RISKS)
    assert marks == [
        RiskMark(
            k="churn",
            label=LABELS["churn"],
            lines=[],
            p=0.82,
            basis="Jev: вероятность 0,82 при пороге 0,5; номера реплик Jev не возвращает",
        )
    ]


def test_cache_key_changes_with_risk_markers() -> None:
    d = prototype_dialogs()[0]
    assert product_key(PRODUCTS, d, RISKS) != product_key(PRODUCTS, d, RISKS[:1])
