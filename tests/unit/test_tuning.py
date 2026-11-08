"""Настройка чек-листа без модели: шкала оценок, «что если» и нормировка весов (чистые функции)."""

import json
from typing import Any

import pytest

from cqa.domain.models import Appeal, Checklist, Criterion, Dialog, Question
from cqa.domain.review import effective_answers
from cqa.domain.scoring import total
from cqa.domain.tuning import Band, Bands, band_errors, band_of, normalize, simulate
from fakes import FIXTURES

BANDS = [
    Band(min=90, label="Отлично", tone="ok"),
    Band(min=75, label="Хорошо"),
    Band(min=60, label="Требует внимания", tone="warn"),
    Band(min=0, label="Критично", tone="risk"),
]


# --- шкала оценок ---


@pytest.mark.parametrize(
    ("t", "label"),
    [
        (100, "Отлично"),
        (90, "Отлично"),
        (89.99, "Хорошо"),
        (75, "Хорошо"),
        (74.99, "Требует внимания"),
        (60, "Требует внимания"),
        (59.99, "Критично"),
        (0, "Критично"),
    ],
)
def test_band_is_the_first_whose_lower_bound_the_total_reaches(t: float, label: str) -> None:
    band = band_of(BANDS, t)
    assert band is not None and band.label == label


def test_dialog_without_total_has_no_band() -> None:
    assert band_of(BANDS, None) is None


def test_valid_bands_have_no_errors() -> None:
    assert band_errors(Bands(bands=BANDS, why="Границы согласованы с руководством.")) == {}


def test_band_errors_are_field_level_russian_messages() -> None:
    bad = Bands(
        why=" ",
        bands=[
            Band(min=75, label="Хорошо"),
            Band(min=90, label="Отлично"),
            Band(min=120, label="Хорошо"),
            Band(min=10, label=" "),
        ],
    )

    errors = band_errors(bad)

    assert set(errors) == {
        "why",
        "bands.1.min",
        "bands.2.min",
        "bands.2.label",
        "bands.3.label",
        "bands.3.min",
    }
    assert errors["bands.1.min"] == (
        "Оценка 2: граница 90 должна быть меньше границы оценки 1 (75) — "
        "оценки идут от лучшей к худшей и не пересекаются"
    )
    assert errors["bands.2.min"] == "Оценка 3: граница 120 вне диапазона 0–100"
    assert errors["bands.2.label"] == "Оценка 3: название «Хорошо» уже есть у оценки 1"
    assert errors["bands.3.min"] == (
        "Оценка 4: последняя граница должна быть 0, иначе итог ниже 10 останется без оценки"
    )


def test_empty_bands_is_an_error() -> None:
    assert band_errors(Bands(bands=[], why="x")) == {"bands": "Нужна хотя бы одна оценка с границей 0"}


# --- «что если» ---


def fixture() -> tuple[Checklist, list[Dialog], dict[str, Any]]:
    s = json.loads((FIXTURES / "analytics_state.json").read_text(encoding="utf-8"))
    dialogs = [Dialog.model_validate(d) for d in s["dialogs"]]
    appeals = [Appeal.model_validate(a) for a in s["appeals"]]
    return (
        Checklist.model_validate(s["checklist"]),
        dialogs,
        {d.id: effective_answers(d, appeals) for d in dialogs},
    )


def edit(cl: Checklist, cid: str, **update: Any) -> Checklist:
    return cl.model_copy(
        update={"criteria": [c.model_copy(update=update) if c.id == cid else c for c in cl.criteria]}
    )


def row(sim: dict[str, Any], dialog_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in sim["dialogs"] if r["id"] == dialog_id)
    return found


def test_weight_change_recomputes_totals_and_names_the_weight_as_the_reason() -> None:
    cl, dialogs, answers = fixture()
    new = edit(cl, "05", w=30)

    sim = simulate(cl, new, dialogs, answers, answers, BANDS)

    r = row(sim, "p1-ru-003")
    assert (r["before"], r["after"], r["delta"]) == (41.0, 35.65, -5.35)
    assert r["why"] == ["вес «Эмпатия и клиентоориентированность» 15 → 30"]
    assert r["text"] == "Итог: 41,00 → 35,65, потому что вес «Эмпатия и клиентоориентированность» 15 → 30"
    assert sim["weights"] == [
        {
            "id": "05",
            "name": "Эмпатия и клиентоориентированность",
            "from": 15,
            "to": 30,
            "share_from": 15.0,
            "share_to": 26.09,
        }
    ]
    assert sim["pending"] == [] and sim["removed"] == []


def test_weight_of_a_criterion_answered_na_does_not_change_that_dialog() -> None:
    cl, dialogs, answers = fixture()

    sim = simulate(cl, edit(cl, "07", w=50), dialogs, answers, answers, BANDS)

    r = row(sim, "p1-ru-025")  # 07 — N/A
    assert (r["delta"], r["why"]) == (0, [])
    assert r["text"] == f"Итог не меняется: {r['before']:.2f}".replace(".", ",")


def test_meaning_change_leaves_the_criterion_pending_and_totals_without_it() -> None:
    cl, dialogs, answers = fixture()
    new = edit(cl, "04", text="Новый текст")
    after = {d: {cid: a for cid, a in ans.items() if cid != "04"} for d, ans in answers.items()}

    sim = simulate(cl, new, dialogs, answers, after, BANDS)

    r = row(sim, "p1-ru-022")
    assert r["after"] == total(new, after["p1-ru-022"])
    assert r["why"] == [
        "«Корректная и полная консультация» ждёт новой оценки (изменено: текст), до неё не входит в итог"
    ]
    assert sim["pending"] == [
        {"id": "04", "name": "Корректная и полная консультация", "why": "изменено: текст", "dialogs": 10}
    ]


def test_removed_criterion_no_longer_counts_where_it_applied() -> None:
    cl, dialogs, answers = fixture()
    new = cl.model_copy(update={"criteria": [c for c in cl.criteria if c.id != "07"]})

    sim = simulate(cl, new, dialogs, answers, answers, BANDS)

    assert row(sim, "p1-ru-003")["why"] == ["«Завершение» удалён: ответ «Нет» больше не входит в итог"]
    assert row(sim, "p1-ru-025")["why"] == []  # там 07 — N/A
    assert sim["removed"] == [{"id": "07", "name": "Завершение"}]


def test_rules_change_sends_the_whole_checklist_to_new_evaluation() -> None:
    cl, dialogs, answers = fixture()
    new = cl.model_copy(update={"rules": "Новые правила"})

    sim = simulate(cl, new, dialogs, answers, {d.id: {} for d in dialogs}, BANDS)

    r = row(sim, "call-024")
    assert r["after"] is None and r["band_after"] is None
    assert r["why"] == ["изменены общие правила: все критерии ждут новой оценки"]
    assert [p["id"] for p in sim["pending"]] == [c.id for c in cl.criteria]


def test_summary_groups_and_band_moves_follow_the_real_formula() -> None:
    cl, dialogs, answers = fixture()
    new = edit(cl, "05", w=30)

    sim = simulate(cl, new, dialogs, answers, answers, BANDS)

    before = {d.id: total(cl, answers[d.id]) for d in dialogs}
    after = {d.id: total(new, answers[d.id]) for d in dialogs}
    s = sim["summary"]
    assert (s["dialogs"], s["scored_before"], s["scored_after"]) == (10, 10, 10)
    assert s["avg_before"] == 81.22  # как средний итог отчёта для руководства на той же фикстуре
    assert s["changed"] == sum(before[k] != after[k] for k in before)
    chats = next(g for g in sim["groups"]["ch"] if g["key"] == "chat")
    assert (chats["label"], chats["n"]) == ("Чат", 9)
    moves: dict[tuple[str, str], int] = {}
    for k in before:
        b0, b1 = band_of(BANDS, before[k]), band_of(BANDS, after[k])
        assert b0 is not None and b1 is not None
        if b0.label != b1.label:
            moves[(b0.label, b1.label)] = moves.get((b0.label, b1.label), 0) + 1
    assert {(m["from"], m["to"]): m["n"] for m in sim["moves"]} == moves
    assert all(m["text"] + "." in sim["findings"] for m in sim["moves"])
    assert sim["findings"][0].startswith("Средний итог: 81,22 → ")


def test_band_move_sentence_agrees_with_the_number() -> None:
    cl, dialogs, answers = fixture()
    one = [d for d in dialogs if d.id == "p1-ru-029"]  # 76,00 → 66,09

    sim = simulate(cl, edit(cl, "05", w=30), one, answers, answers, BANDS)

    assert sim["moves"] == [
        {
            "from": "Хорошо",
            "to": "Требует внимания",
            "n": 1,
            "text": "1 диалог перейдёт из „Хорошо“ в „Требует внимания“",
        }
    ]


# --- нормировка весов ---


def checklist(*weights: float) -> Checklist:
    criteria = [
        Criterion(id=f"c{i}", sec=0, name=f"К{i}", type="bool", w=w, text="Да — …")
        for i, w in enumerate(weights)
    ]
    flag = Criterion(
        id="f", sec=0, name="Флаг", type="flag", w=0, text="…", questions=[Question(k="x", label="X")]
    )
    return Checklist(version=1, rules="", sections=["Раздел"], criteria=[*criteria, flag])


def weights(out: dict[str, Any]) -> list[float]:
    return [c.w for c in out["checklist"].criteria if c.type != "flag"]


def test_normalize_rescales_to_exactly_100_giving_the_rounding_rest_to_largest_remainders() -> None:
    out = normalize(checklist(3, 3, 3, 3, 3, 3, 3))  # 100 / 7 = 14,29 каждому

    assert weights(out) == [15, 15, 14, 14, 14, 14, 14]
    assert sum(weights(out)) == 100
    assert out["changes"][0] == {"id": "c0", "name": "К0", "from": 3, "to": 15, "exact": 14.29}
    assert (
        "Остаток округления 2 отдан по одному критериям с наибольшей дробной частью: «К0», «К1»."
        in out["explanation"]
    )


def test_normalize_prefers_the_larger_remainder_then_the_heavier_criterion() -> None:
    assert weights(normalize(checklist(1, 1, 1))) == [34, 33, 33]
    assert weights(normalize(checklist(10, 20, 30))) == [17, 33, 50]  # 16,67 / 33,33 / 50


def test_normalize_keeps_weights_that_already_sum_to_100() -> None:
    out = normalize(checklist(10, 15, 20, 20, 15, 15, 5))

    assert weights(out) == [10, 15, 20, 20, 15, 15, 5]
    assert out["changes"] == []
    assert out["explanation"].startswith("Сумма весов уже 100")


def test_normalize_splits_equally_when_all_weights_are_zero() -> None:
    out = normalize(checklist(0, 0, 0))

    assert weights(out) == [34, 33, 33]
    assert out["explanation"].startswith("Сумма весов 0")


def test_normalize_reports_share_of_each_scored_criterion_and_leaves_flags_alone() -> None:
    out = normalize(checklist(1, 3))

    assert out["shares"] == {"c0": 25.0, "c1": 75.0}
    assert out["checklist"].criteria[-1].w == 0
