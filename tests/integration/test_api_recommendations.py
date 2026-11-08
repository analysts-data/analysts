"""GET /api/recommendations: четыре адресата из текущего состояния, решения и сохранённая интонация."""

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import Dialog
from cqa.domain.review import fingerprint
from fakes import prototype_checklist


def evaluate(store: Store, dialog: Dialog) -> None:
    cl = prototype_checklist()
    for c in cl.criteria:
        store.add_result(dialog.id, c.id, cl.version, fingerprint(cl, c, dialog.ch), dialog.res[c.id])


@pytest.mark.parametrize("audience", ["qa", "manager", "checklist"])
def test_each_audience_answers_json_with_params_and_lists(client: TestClient, audience: str) -> None:
    body = client.get(f"/api/recommendations?for={audience}").json()

    assert body["for"] == audience
    assert body["params"] and all(p["why"] for p in body["params"])
    assert isinstance(body["insufficient"], list)


def test_qa_queue_uses_current_results_and_cached_prosody(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    for d in dialogs:
        evaluate(store, d)
    client_line = next(ln.n for ln in dialogs[0].lines or [] if getattr(ln, "who", "") == "client")
    store.set_prosody("call-024", {"lines": [{"n": client_line, "flags": ["raised"]}], "summary": []})

    items = client.get("/api/recommendations?for=qa").json()["items"]

    call = next(i for i in items if i["id"] == "call-024")
    assert "tone" in [r["k"] for r in call["reasons"]]
    assert client_line in call["basis"]["dialogs"][0]["lines"]


def test_operator_needs_id_and_unknown_operator_is_404(client: TestClient) -> None:
    assert client.get("/api/recommendations?for=operator").status_code == 422
    assert client.get("/api/recommendations?for=operator&id=Никто").status_code == 404


def test_unknown_audience_is_422(client: TestClient) -> None:
    assert client.get("/api/recommendations?for=boss").status_code == 422
