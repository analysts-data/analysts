"""Шкала оценок, «что если», нормировка весов, шаблоны и готовые чек-листы через HTTP."""

import copy
from typing import Any

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import Dialog
from cqa.domain.review import fingerprint
from fakes import prototype_checklist


def evaluate(store: Store, dialog: Dialog) -> None:
    cl = prototype_checklist()
    for c in cl.criteria:
        store.add_result(dialog.id, c.id, cl.version, fingerprint(cl, c, dialog.ch), dialog.res[c.id])


def current(client: TestClient) -> dict[str, Any]:
    checklist: dict[str, Any] = client.get("/api/state").json()["checklist"]
    return checklist


def with_criterion(draft: dict[str, Any], cid: str, **update: Any) -> dict[str, Any]:
    out = copy.deepcopy(draft)
    for c in out["criteria"]:
        if c["id"] == cid:
            c.update(update)
    return out


BANDS = {
    "why": "Согласовано с руководством 08.11.",
    "bands": [
        {"min": 85, "label": "Отлично", "tone": "ok"},
        {"min": 50, "label": "Норма"},
        {"min": 0, "label": "Плохо", "tone": "risk"},
    ],
}


# --- шкала оценок ---


def test_bands_default_comes_with_justification_and_is_marked_default(client: TestClient) -> None:
    body = client.get("/api/bands").json()

    assert (body["source"], body["saved_at"]) == ("default", None)
    assert body["why"].strip()
    assert [b["min"] for b in body["bands"]] == [90, 75, 60, 0]
    assert body["bands"][0] == {"min": 90, "label": "Отлично", "tone": "ok"}


def test_put_bands_saves_them_over_the_default(client: TestClient) -> None:
    saved = client.put("/api/bands", json=BANDS)

    assert saved.status_code == 200
    body = client.get("/api/bands").json()
    assert body["source"] == "saved" and body["saved_at"]
    assert body["bands"][1] == {"min": 50, "label": "Норма", "tone": None}
    assert body["why"] == BANDS["why"]


def test_put_bands_rejects_overlap_with_field_level_messages(client: TestClient) -> None:
    bad = copy.deepcopy(BANDS)
    bad["bands"][1]["min"] = 85

    response = client.put("/api/bands", json=bad)

    assert response.status_code == 422
    body = response.json()
    assert set(body["fields"]) == {"bands.1.min"}
    assert body["detail"] == body["fields"]["bands.1.min"]
    assert client.get("/api/bands").json()["source"] == "default"


# --- «что если» ---


def test_simulate_returns_new_totals_without_saving(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    evaluate(store, dialogs[0])  # call-024, итог 82,94
    draft = with_criterion(current(client), "05", w=30)

    response = client.post("/api/checklist/simulate", json=draft)

    assert response.status_code == 200
    sim = response.json()
    call = next(r for r in sim["dialogs"] if r["id"] == "call-024")
    assert call["before"] == 82.94 and call["after"] > call["before"]
    assert call["why"] == ["вес «Эмпатия и клиентоориентированность» 15 → 30"]
    assert sim["summary"]["avg_before"] == 82.94
    assert sim["save_errors"] == {}
    assert current(client)["version"] == 3


def test_simulate_takes_answers_by_the_draft_meaning(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    evaluate(store, dialogs[0])
    draft = with_criterion(current(client), "04", text="Новый текст")

    sim = client.post("/api/checklist/simulate", json=draft).json()

    assert sim["pending"][0]["id"] == "04" and sim["pending"][0]["dialogs"] == 2
    call = next(r for r in sim["dialogs"] if r["id"] == "call-024")
    assert call["why"][0].startswith("«Корректная и полная консультация» ждёт новой оценки")


def test_simulate_lists_what_would_block_the_save(client: TestClient) -> None:
    draft = with_criterion(current(client), "05", channel="chat")

    sim = client.post("/api/checklist/simulate", json=draft).json()

    assert sim["save_errors"] == {"criteria.4.na": "Критерий 05: для канала chat нужен na: true"}


# --- нормировка ---


def test_normalize_returns_draft_with_weights_summing_to_100_without_saving(client: TestClient) -> None:
    draft = with_criterion(current(client), "05", w=30)

    out = client.post("/api/checklist/normalize", json=draft).json()

    assert sum(c["w"] for c in out["checklist"]["criteria"] if c["type"] != "flag") == 100
    assert out["checklist"]["version"] == 3
    assert round(sum(out["shares"].values()), 6) == 100
    assert out["explanation"] and out["changes"]
    assert current(client)["criteria"][4]["w"] == 15


# --- шаблоны и готовые чек-листы ---


def test_templates_filter_by_tag(client: TestClient) -> None:
    every = client.get("/api/criteria/templates").json()
    calls = client.get("/api/criteria/templates", params={"tag": "звонки"}).json()

    assert calls["templates"] and all("звонки" in t["tags"] for t in calls["templates"])
    assert len(calls["templates"]) < len(every["templates"])


def test_presets_are_whole_checklists_for_json_import(client: TestClient) -> None:
    presets = client.get("/api/checklist/presets").json()

    assert presets[0]["official"] is True
    for p in presets:
        assert set(p["checklist"]) >= {"rules", "sections", "criteria"}


# --- ошибки сохранения по полям ---


def test_put_checklist_422_names_the_field(client: TestClient) -> None:
    draft = with_criterion(current(client), "05", channel="chat")

    response = client.put("/api/checklist", json=draft)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Критерий 05: для канала chat нужен na: true",
        "fields": {"criteria.4.na": "Критерий 05: для канала chat нужен na: true"},
    }


def test_put_checklist_rejects_negative_weight(client: TestClient) -> None:
    response = client.put("/api/checklist", json=with_criterion(current(client), "05", w=-5))

    assert response.status_code == 422
    assert response.json()["fields"] == {"criteria.4.w": "Критерий 05: вес -5 меньше нуля"}


# --- отчёт ---


def test_report_counts_dialogs_by_band(client: TestClient, store: Store, dialogs: list[Dialog]) -> None:
    evaluate(store, dialogs[0])  # 82,94 — «Хорошо» по умолчанию

    bands = client.get("/api/report?format=json").json()["summary"]["bands"]

    assert [(b["label"], b["n"]) for b in bands] == [
        ("Отлично", 0),
        ("Хорошо", 1),
        ("Требует внимания", 0),
        ("Критично", 0),
    ]
    assert bands[1]["share"] == 1.0
