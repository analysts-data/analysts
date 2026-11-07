from typing import Any

from fastapi.testclient import TestClient


def call_024(client: TestClient) -> dict[str, Any]:
    return next(d for d in client.get("/api/state").json()["dialogs"] if d["id"] == "call-024")


def test_reviewed_mark_is_set_and_cleared(client: TestClient) -> None:
    assert client.post("/api/dialogs/call-024/reviewed", json={"reviewed": True}).json() == {"ok": True}
    assert call_024(client)["reviewed"] is True
    assert client.post("/api/dialogs/call-024/reviewed", json={"reviewed": False}).json() == {"ok": True}
    assert call_024(client)["reviewed"] is False


def test_reviewed_without_field_is_rejected(client: TestClient) -> None:
    assert client.post("/api/dialogs/call-024/reviewed", json={}).status_code == 422
    assert call_024(client)["reviewed"] is False


def test_reviewed_of_unknown_dialog_is_404(client: TestClient) -> None:
    response = client.post("/api/dialogs/nope/reviewed", json={"reviewed": True})
    assert response.status_code == 404
    assert response.json() == {"detail": "Диалог nope не найден"}
