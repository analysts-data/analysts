"""Сотрудник диалога: загрузка с полем, ручное и массовое назначение, сводка, отчёт, экранирование."""

import json
import sqlite3

from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import Dialog
from cqa.domain.review import fingerprint
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FIXTURES, prototype_checklist

XSS = "<img src=x onerror=alert(1)>"


def evaluate(store: Store, dialog: Dialog) -> None:
    cl = prototype_checklist()
    for c in cl.criteria:
        store.add_result(dialog.id, c.id, cl.version, fingerprint(cl, c, dialog.ch), dialog.res[c.id])


def operators_in_state(client: TestClient) -> dict[str, str | None]:
    return {d["id"]: d.get("operator") for d in client.get("/api/state").json()["dialogs"]}


def test_upload_maps_operator_field_of_the_record(settings: Settings, conn: sqlite3.Connection) -> None:
    envelope = json.loads((FIXTURES / "org_payload.json").read_text(encoding="utf-8"))
    first = envelope["data"]["records"][0]
    first["agent_name"] = "Сотрудник из файла"
    client = TestClient(create_app(settings, conn=conn))

    assert client.post("/api/datasets/upload", content=json.dumps(envelope)).status_code == 200

    assert operators_in_state(client)[first["conversation_id"]] == "Сотрудник из файла"


def test_put_operator_sets_and_clears(client: TestClient) -> None:
    put = client.put("/api/dialogs/p1-ru-003/operator", json={"operator": "  Сотрудник А "})
    assert (put.status_code, put.json()) == (200, {"operator": "Сотрудник А"})
    assert operators_in_state(client) == {"call-024": None, "p1-ru-003": "Сотрудник А"}

    assert client.put("/api/dialogs/p1-ru-003/operator", json={"operator": None}).json() == {"operator": None}
    assert client.put("/api/dialogs/p1-ru-003/operator", json={"operator": " "}).json() == {"operator": None}
    assert operators_in_state(client)["p1-ru-003"] is None


def test_put_operator_unknown_dialog_is_404_and_bad_body_422(client: TestClient) -> None:
    assert client.put("/api/dialogs/nope/operator", json={"operator": "Х"}).status_code == 404
    assert client.put("/api/dialogs/p1-ru-003/operator", json={"operator": 5}).status_code == 422


def test_csv_import_updates_known_and_lists_unknown_ids(client: TestClient) -> None:
    body = "conversation_id;operator\ncall-024;Сотрудник А\nnope;Сотрудник Б\np1-ru-003;Сотрудник Б\n"
    response = client.post(
        "/api/operators/import", content=body.encode(), headers={"Content-Type": "text/csv"}
    )

    assert (response.status_code, response.json()) == (200, {"updated": 2, "unknown_ids": ["nope"]})
    assert operators_in_state(client) == {"call-024": "Сотрудник А", "p1-ru-003": "Сотрудник Б"}


def test_csv_import_empty_or_not_utf8_is_422(client: TestClient) -> None:
    assert client.post("/api/operators/import", content=b"").status_code == 422
    assert client.post("/api/operators/import", content="a;Б".encode("cp1251")).status_code == 422


def test_operators_list_and_card(client: TestClient, store: Store, dialogs: list[Dialog]) -> None:
    evaluate(store, dialogs[0])  # call-024: 82,94
    client.put("/api/dialogs/call-024/operator", json={"operator": "Сотрудник А"})

    rows = client.get("/api/operators").json()
    card = client.get("/api/operators/Сотрудник А").json()

    assert [(r["operator"], r["dialogs"], r["scored"], r["avg_total"]) for r in rows] == [
        ("Сотрудник А", 1, 1, 82.94),
        ("Не указан", 1, 0, None),
    ]
    assert set(rows[0]) == {
        "operator", "dialogs", "scored", "avg_total", "gross_errors", "needs_review", "appeals_open",
        "weakest", "trend",
    }  # fmt: skip
    assert (card["dialog_ids"], card["trend"][0]["day"]) == (["call-024"], dialogs[0].at[:5])
    assert isinstance(card["reasons"], list)
    assert client.get("/api/operators/Не указан").json()["dialog_ids"] == ["p1-ru-003"]
    assert client.get("/api/operators/Никто").status_code == 404


def test_report_section_filter_and_escaped_name(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    for d in dialogs:
        evaluate(store, d)
    client.put("/api/dialogs/call-024/operator", json={"operator": XSS})
    client.put("/api/dialogs/p1-ru-003/operator", json={"operator": "Сотрудник Б"})

    html = client.get("/api/report").text
    filtered = client.get("/api/report", params={"format": "json", "operator": "Сотрудник Б"}).json()

    assert "По сотрудникам" in html
    assert XSS not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert (filtered["summary"]["dialogs"], filtered["filters"]["operator"]) == (1, "Сотрудник Б")
