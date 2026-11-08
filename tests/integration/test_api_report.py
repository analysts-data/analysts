"""GET /api/report: отчёт для руководства в html, json и md из текущего состояния."""

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


@pytest.mark.parametrize(
    ("fmt", "media", "start"),
    [
        ("html", "text/html; charset=utf-8", "<!doctype html>"),
        ("md", "text/markdown; charset=utf-8", "# Отчёт для руководства\n"),
    ],
)
def test_report_formats_have_content_type(client: TestClient, fmt: str, media: str, start: str) -> None:
    response = client.get(f"/api/report?format={fmt}")

    assert response.status_code == 200
    assert response.headers["content-type"] == media
    assert response.text.startswith(start)
    assert "Нет оценённых диалогов" in response.text


def test_report_defaults_to_printable_html(client: TestClient) -> None:
    assert client.get("/api/report").headers["content-type"] == "text/html; charset=utf-8"


def test_report_json_follows_current_results_and_filters(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    evaluate(store, dialogs[0])  # call-024

    every = client.get("/api/report?format=json")
    chats = client.get("/api/report?format=json&ch=chat").json()

    assert every.headers["content-type"] == "application/json"
    summary = every.json()["summary"]
    assert (summary["dialogs"], summary["scored"], summary["avg_total"]) == (2, 1, 82.94)
    assert (chats["summary"]["scored"], chats["filters"]) == (
        0,
        {"lang": None, "ch": "chat", "operator": None},
    )


def test_report_bad_format_or_channel_is_422(client: TestClient) -> None:
    assert client.get("/api/report?format=pdf").status_code == 422
    assert client.get("/api/report?ch=fax").status_code == 422
