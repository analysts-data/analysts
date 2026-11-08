"""GET /api/checklist/export и /api/checklist/diff, POST /api/checklist/diff."""

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient


def current(client: TestClient) -> dict[str, Any]:
    return client.get("/api/state").json()["checklist"]


def save_v4(client: TestClient) -> dict[str, Any]:
    """v4: вес 06 = 10, текст 04 новый."""
    draft = copy.deepcopy(current(client))
    for c in draft["criteria"]:
        if c["id"] == "06":
            c["w"] = 10
        if c["id"] == "04":
            c["text"] = "Новый текст"
    assert client.put("/api/checklist", json=draft).json()["version"] == 4
    return draft


def test_export_defaults_to_current_version_as_json_attachment(client: TestClient) -> None:
    response = client.get("/api/checklist/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="checklist-v3.json"'
    assert response.json() == current(client)


@pytest.mark.parametrize(
    ("fmt", "media", "how", "start"),
    [
        ("csv", "text/csv; charset=utf-8", "attachment", "﻿ID;"),
        ("md", "text/markdown; charset=utf-8", "attachment", "# Чек-лист v3"),
        ("html", "text/html; charset=utf-8", "inline", "<!doctype html>"),
    ],
)
def test_export_formats_have_content_type_and_disposition(
    client: TestClient, fmt: str, media: str, how: str, start: str
) -> None:
    response = client.get(f"/api/checklist/export?v=3&format={fmt}")

    assert response.status_code == 200
    assert response.headers["content-type"] == media
    assert response.headers["content-disposition"] == f'{how}; filename="checklist-v3.{fmt}"'
    assert response.text.startswith(start)


def test_export_reads_an_older_version(client: TestClient) -> None:
    v3 = current(client)
    save_v4(client)

    assert client.get("/api/checklist/export?v=3").json() == v3
    assert client.get("/api/checklist/export").json()["version"] == 4


def test_export_unknown_version_is_404_and_bad_format_is_422(client: TestClient) -> None:
    assert client.get("/api/checklist/export?v=99").status_code == 404
    assert client.get("/api/checklist/export?format=xlsx").status_code == 422


def test_diff_between_versions_as_json_and_markdown(client: TestClient) -> None:
    save_v4(client)

    d = client.get("/api/checklist/diff?from=3&to=4").json()
    md = client.get("/api/checklist/diff?from=3&to=4&format=md")

    assert d["rules_changed"] is False and d["added"] == [] and d["removed"] == []
    assert [(c["id"], c["reevaluate"]) for c in d["changed"]] == [("04", True), ("06", False)]
    assert md.headers["content-type"] == "text/markdown; charset=utf-8"
    assert md.text.startswith("# Что изменится: v3 → v4\n")


def test_diff_to_defaults_to_current_version(client: TestClient) -> None:
    save_v4(client)

    assert (
        client.get("/api/checklist/diff?from=3").json()
        == client.get("/api/checklist/diff?from=3&to=4").json()
    )


def test_diff_unknown_version_is_404_and_bad_format_is_422(client: TestClient) -> None:
    assert client.get("/api/checklist/diff?from=3&to=9").status_code == 404
    assert client.get("/api/checklist/diff?from=3&format=html").status_code == 422


def test_post_diff_compares_draft_with_current_version(client: TestClient) -> None:
    draft = copy.deepcopy(current(client))
    draft["criteria"] = [c for c in draft["criteria"] if c["id"] != "07"]

    d = client.post("/api/checklist/diff", json=draft).json()
    md = client.post("/api/checklist/diff?format=md", json=draft).text

    assert [r["id"] for r in d["removed"]] == ["07"]
    assert md.startswith("# Что изменится: v3 → v4\n")
    assert current(client)["version"] == 3  # сравнение ничего не сохраняет
