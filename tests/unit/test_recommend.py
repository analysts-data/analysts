"""Рекомендации: явные правила на маленьком наборе, пороги выборки, порядок и обоснование каждого пункта."""

from typing import Any

from cqa.domain.models import Answer, Appeal, Checklist, CriterionResult, Dialog, Line, ProductTag
from cqa.domain.recommend import for_checklist, for_manager, for_operator, for_qa

CL = Checklist.model_validate(
    {
        "version": 1,
        "rules": "",
        "sections": ["s"],
        "criteria": [
            {"id": "a", "sec": 0, "name": "Приветствие", "type": "bool", "w": 10, "text": "t"},
            {"id": "b", "sec": 0, "name": "Решение", "type": "scale", "w": 30, "steps": [0, 5, 10],
             "text": "t"},
            {"id": "c", "sec": 0, "name": "Проверка", "type": "bool", "w": 60, "na": True,
             "naCond": "Нет вопроса", "text": "t"},
            {"id": "f", "sec": 0, "name": "Грубое", "type": "flag", "w": 0, "signal": "risk", "text": "t",
             "questions": [{"k": "insult", "label": "Оскорбление"}]},
        ],
    }
)  # fmt: skip
OWNERS = {"Нет срока": "Инструкция", "Нет проверки": "Сервис"}
LOST_B = {"tag": "Нет срока", "ev": [5], "seg": "conv", "quote": "Ждите"}


def R(a: Answer, **kw: Any) -> CriterionResult:
    return CriterionResult(a=a, **{"ev": [2], **kw})


def dlg(id: str, op: str | None = None, product: str | None = None, lang: str = "RU", **res: Any) -> Dialog:
    base: dict[str, Any] = {"a": R("yes"), "b": R(10), "c": R("yes"), "f": R({"insult": False})}
    reviewed, ch = res.pop("reviewed", False), res.pop("ch", "chat")
    base.update({k: v if isinstance(v, CriterionResult) else R(v) for k, v in res.items()})
    lines = [Line(n=n, t=float(n), who="client" if n % 2 else "operator", text="…") for n in range(1, 7)]
    d = Dialog(id=id, ch=ch, lang=lang, at="", lines=lines, res=base, reviewed=reviewed)
    tag = (
        ProductTag(status="done", id=product.lower(), name=product) if product else None
    )  # тема — Dialog.product
    return d.model_copy(update={"operator": op, "product": tag})


def world() -> list[Dialog]:
    ds = [
        dlg("a1", "Анна", "Карта", b=R(0, **LOST_B, better="Назовите срок: «ответим до 18:00»")),
        *[dlg(f"a{i}", "Анна", "Карта", b=R(0, **LOST_B)) for i in (2, 3, 4)],
        dlg("a5", "Анна", "Карта"),
        dlg("a6", "Анна", "Карта"),
        *[dlg(f"b{i}", "Борис", "Депозит", "KZ") for i in range(1, 6)],
        dlg("b6", "Борис", "Депозит", "KZ", c=R("no", tag="Нет проверки")),
        dlg("v1", "Вера", "Карта", b=R(10, ev=[4], quote="Ответим до 18:00")),
        *[dlg(f"v{i}", "Вера", "Карта") for i in range(2, 7)],
        dlg("g1", "Гоша", "Карта", b=R(0, **LOST_B)),
        dlg("g2", "Гоша", "Карта", b=R(0, **LOST_B)),
        *[dlg(f"k0{i}", product="Кредит") for i in range(1, 6)],
        *[dlg(f"k{i:02}", product="Кредит", c=R("no", tag="Нет проверки", ev=[6])) for i in range(6, 11)],
        dlg("q-flag", "Борис", lang="EN", f=R({"insult": True}, ev=[3])),
        dlg("q-flag-rev", lang="EN", f=R({"insult": True}), reviewed=True),
        dlg("q-alt", lang="EN", b=R(5, alt=10, tag="Неполно", ev=[4])),
        dlg("q-ev", lang="EN", a=R("yes", evFail=True, ev=[1])),
        dlg(
            "q-jev",
            lang="EN",
            a=R("no", evFail=True, model="jev-latest", why="Ответ Jev с вероятностью 0,41"),
        ),
        dlg("q-tone", lang="EN", ch="call"),
    ]
    return [d.model_copy(update={"at": f"07.11 {10 + i // 60:02}:{i % 60:02}"}) for i, d in enumerate(ds)]


def decided(dlg_id: str, status: str) -> Appeal:
    return Appeal.model_validate(
        {"id": f"x-{dlg_id}", "kind": "appeal", "dlg": dlg_id, "cid": "a", "from": "yes", "ask": "no",
         "to": "yes", "by": "Оператор", "at": "07.11 12:00", "status": status}
    )  # fmt: skip


APPEALS = [decided(f"k0{i}", "changed" if i <= 2 else "confirmed") for i in range(1, 6)]
TONE = {"q-tone": {"lines": [{"n": 3, "flags": ["raised"]}, {"n": 4, "flags": ["raised"]}], "summary": []}}


def every_item(rec: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("items", "actions", "operators", "trends")
    return [i for k in keys for i in rec.get(k, [])] + ([rec["strength"]] if rec.get("strength") else [])


def assert_explained(rec: dict[str, Any]) -> None:
    """Нет рекомендации без доказательств: почему словами, правило, числа, диалоги."""
    items = every_item(rec)
    assert items
    for i in items:
        assert i["why"] and i["basis"]["rule"] and i["basis"]["numbers"], i
        assert i["basis"]["dialogs"] and all(d["id"] for d in i["basis"]["dialogs"]), i
    assert {p["name"] for p in rec["params"]} and all(p["why"] for p in rec["params"])


# --- Оператору ---


def test_operator_coaching_names_skill_behind_team_with_numbers_own_dialogs_and_lines() -> None:
    rec = for_operator(CL, world(), [], "Анна")
    assert rec is not None

    assert [i["cid"] for i in rec["items"]] == ["b"]  # остальные критерии не ниже коллег
    skill = rec["items"][0]
    n = skill["basis"]["numbers"]
    # коллеги — Борис 7, Вера 6, Гоша 2 (оба «0»): 13 из 15
    assert (n["share"], n["team_share"], n["n"], n["team_n"]) == (0.3333, 0.8667, 6, 15)
    assert [(d["id"], d["lines"], d["seg"], d["quote"]) for d in skill["basis"]["dialogs"]] == [
        ("a1", [5], "conv", "Ждите"),
        ("a2", [5], "conv", "Ждите"),
    ]
    assert "0,33" in skill["why"] and "0,87" in skill["why"]
    assert_explained(rec)


def test_operator_better_phrasing_comes_from_own_results() -> None:
    skill = for_operator(CL, world(), [], "Анна")["items"][0]  # type: ignore[index]

    assert skill["better"] == [{"id": "a1", "text": "Назовите срок: «ответим до 18:00»"}]


def test_colleague_samples_got_max_on_same_product_and_language_with_stored_quote() -> None:
    skill = for_operator(CL, world(), [], "Анна")["items"][0]  # type: ignore[index]

    # Вера — тот же продукт и язык; у Бориса другой продукт и язык, у Гоши та же ошибка
    assert [(p["id"], p["operator"], p["lines"], p["quote"], p["match"]) for p in skill["peers"]] == [
        ("v1", "Вера", [4], "Ответим до 18:00", ["продукт", "язык"]),
        ("v2", "Вера", [2], None, ["продукт", "язык"]),
    ]


def test_operator_strength_is_best_own_criterion() -> None:
    rec = for_operator(CL, world(), [], "Анна")

    assert rec is not None and rec["strength"]["cid"] == "c"  # доля 1,00, выше коллег (у Бориса «нет»)


def test_operator_with_few_dialogs_gets_insufficient_data_not_advice() -> None:
    rec = for_operator(CL, world(), [], "Гоша")

    assert rec is not None and rec["items"] == [] and rec["strength"] is None
    assert "недостаточно данных (n=2, нужно ≥5)" in [x["text"] for x in rec["insufficient"]]


def test_unknown_operator_is_none() -> None:
    assert for_operator(CL, world(), [], "Никто") is None


# --- Проверяющему ---


def test_qa_queue_follows_explicit_rule_order_and_breaks_ties_deterministically() -> None:
    rec = for_qa(CL, world(), APPEALS, TONE)

    assert [r["k"] for r in rec["rules"]] == [
        "gross", "disagree", "evidence", "jev", "low", "tone", "new_operator", "product_trend",
    ]  # fmt: skip
    # k06–k10: низкий итог и тренд продукта (2 правила), b6: только низкий итог
    assert [i["id"] for i in rec["items"]] == [
        "q-flag", "q-alt", "q-ev", "q-jev", "k06", "k07", "k08", "k09", "k10", "b6", "q-tone", "g1", "g2",
    ]  # fmt: skip
    first = rec["items"][0]
    assert first["rule"] == "gross" and first["reasons"][0]["lines"] == [3]
    assert [r["k"] for r in rec["items"][4]["reasons"]] == ["low", "product_trend"]
    assert rec["items"][10]["reasons"][0]["lines"] == [3]  # реплика 3 клиента; 4 — оператора
    assert_explained(rec)


def test_qa_queue_skips_reviewed_and_decided_pairs() -> None:
    ds = world()
    appeal = decided("q-alt", "confirmed").model_copy(update={"cid": "b", "from_": 5, "to": 5})

    ids = [i["id"] for i in for_qa(CL, ds, [appeal], {})["items"]]

    assert "q-flag-rev" not in ids and "q-alt" not in ids


# --- Руководителю ---


def test_manager_actions_by_owner_and_product_sorted_by_uplift_from_real_formula() -> None:
    rec = for_manager(CL, world(), [], OWNERS)

    top = [
        (a["owner"], a["tag"], a["product"], a["basis"]["numbers"]["dialogs"], a["uplift"])
        for a in rec["actions"]
    ]
    # 5 диалогов × (100 − 40) / 36 оценённых; 6 × (100 − 70) / 36
    assert top == [
        ("Сервис", "Нет проверки", "Кредит", 5, 8.33),
        ("Инструкция", "Нет срока", "Карта", 6, 5.0),
    ]
    assert rec["actions"][1]["title"] == (
        "Обновить инструкцию: 6 диалогов теряют баллы по причине „Нет срока“ (продукт Карта), "
        "потенциальный рост среднего итога +5,00"
    )
    assert_explained(rec)


def test_manager_operators_needing_attention_and_insufficient_small_ones() -> None:
    rec = for_manager(CL, world(), [], OWNERS)

    assert [o["operator"] for o in rec["operators"]] == ["Борис"]  # грубое нарушение в q-flag
    assert any(x["subject"] == "Гоша" and "n=2, нужно ≥5" in x["text"] for x in rec["insufficient"])


def test_manager_trends_down_compare_earlier_and_later_halves() -> None:
    rec = for_manager(CL, world(), [], OWNERS)

    kredit = next(t for t in rec["trends"] if t["key"] == "Кредит")
    n = kredit["basis"]["numbers"]
    assert (n["earlier_avg"], n["later_avg"], n["earlier_n"], n["later_n"]) == (100.0, 40.0, 5, 5)
    drops = [t["basis"]["numbers"]["drop"] for t in rec["trends"]]
    assert drops == sorted(drops, reverse=True)
    assert any(x["subject"] == "продукт Депозит" for x in rec["insufficient"])  # половины по 3


# --- Автору чек-листа ---


def test_checklist_flags_uniform_and_ambiguous_criteria_with_insufficient_samples() -> None:
    rec = for_checklist(CL, world(), APPEALS)

    assert [(i["kind"], i["cid"]) for i in rec["items"]] == [("ambiguous", "a"), ("uniform", "a")]
    amb = rec["items"][0]["basis"]["numbers"]
    assert (amb["decided"], amb["changed"]) == (5, 2)
    assert rec["items"][1]["basis"]["numbers"]["top_share"] == 0.9722  # 35 из 36 — «да»
    assert any("n=1, нужно ≥5" in x["text"] for x in rec["insufficient"])  # одно второе мнение у b
    assert_explained(rec)


def test_checklist_na_overuse() -> None:
    ds = [dlg(f"n{i}", c=R("na")) for i in range(6)] + [dlg("y", c=R("yes"))]

    rec = for_checklist(CL, ds, [])

    na = next(i for i in rec["items"] if i["kind"] == "na")
    assert na["cid"] == "c" and na["basis"]["numbers"]["na_share"] == 0.8571


def test_checklist_weight_vs_impact_suggests_weight_from_loss_share() -> None:
    ds = [dlg(f"w{i}", a=R("no")) for i in range(6)] + [dlg("z", c=R("no"))]

    item = next(i for i in for_checklist(CL, ds, [])["items"] if i["kind"] == "weight")

    n = item["basis"]["numbers"]
    assert (item["cid"], n["weight_share"], n["loss_share"], n["suggested_w"]) == ("a", 0.1, 0.5, 50)
    assert "вес 10" in item["title"] and "50 %" in item["title"]
