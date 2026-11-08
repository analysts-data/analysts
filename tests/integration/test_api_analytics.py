"""GET /api/analytics/<name>: расширенная аналитика из текущего состояния, числа как у отчёта."""

import re

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.analytics import NAMES
from cqa.domain.models import Dialog
from cqa.domain.review import fingerprint
from fakes import prototype_checklist


def evaluate(store: Store, dialog: Dialog) -> None:
    cl = prototype_checklist()
    for c in cl.criteria:
        store.add_result(dialog.id, c.id, cl.version, fingerprint(cl, c, dialog.ch), dialog.res[c.id])


@pytest.mark.parametrize("name", NAMES)
def test_every_endpoint_answers_json_with_n_and_definitions(
    client: TestClient, store: Store, dialogs: list[Dialog], name: str
) -> None:
    evaluate(store, dialogs[0])  # call-024

    response = client.get(f"/api/analytics/{name}")

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["n"], body["min_n"]) == (name, 1, 5)
    assert body["definitions"]["low_n"]


def test_trend_follows_current_results_and_matches_report(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    evaluate(store, dialogs[0])

    [point] = client.get("/api/analytics/trend?by=week").json()["points"]
    summary = client.get("/api/report?format=json").json()["summary"]

    assert (point["n"], point["avg_total"], point["low_n"]) == (summary["scored"], summary["avg_total"], True)
    assert re.fullmatch(r"\d{4}-W\d{2}", point["period"])


def test_filters_reach_the_numbers(client: TestClient, store: Store, dialogs: list[Dialog]) -> None:
    evaluate(store, dialogs[0])

    chats = client.get("/api/analytics/crosstab?ch=chat").json()
    calls = client.get("/api/analytics/crosstab?ch=call&lang=ru").json()
    later = client.get("/api/analytics/heatmap?by=lang&since=2999-01-01").json()

    assert (chats["n"], chats["filters"]["ch"]) == (0, "chat")
    assert [(c["ch"], c["lang"], c["n"]) for c in calls["cells"]] == [("call", "RU", 1)]
    assert (later["n"], later["filters"]["since"]) == (0, "2999-01-01")


def test_drivers_simulate_the_real_formula(client: TestClient, store: Store, dialogs: list[Dialog]) -> None:
    evaluate(store, dialogs[0])

    drivers = client.get("/api/analytics/drivers").json()["drivers"]

    assert all(d["avg_total_if_max"] >= 82.94 for d in drivers)
    assert drivers[0]["uplift"] == max(d["uplift"] for d in drivers)


def test_unknown_name_breakdown_or_bad_date_is_422(client: TestClient) -> None:
    assert client.get("/api/analytics/nope").status_code == 422
    assert client.get("/api/analytics/trend?by=lang").status_code == 422
    assert client.get("/api/analytics/heatmap?by=week").status_code == 422
    assert client.get("/api/analytics/trend?since=07.11").status_code == 422
    assert client.get("/api/analytics/trend?ch=fax").status_code == 422
