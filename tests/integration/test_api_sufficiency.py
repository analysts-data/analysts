"""GET/PUT /api/sufficiency: исходы правил достаточности данных — данные, меняются из интерфейса."""

from fastapi.testclient import TestClient


def test_outcomes_have_conservative_defaults_and_can_be_changed(client: TestClient) -> None:
    rules = client.get("/api/sufficiency").json()["rules"]
    assert {r["id"] for r in rules if r["default"] == "block"} == {"bot_only", "no_operator"}
    assert client.put("/api/sufficiency", json={"truncated": "info"}).status_code == 200
    saved = {r["id"]: r["outcome"] for r in client.get("/api/sufficiency").json()["rules"]}
    assert saved["truncated"] == "info"
    assert client.put("/api/sufficiency", json={"nope": "flag"}).status_code == 422
    assert client.put("/api/sufficiency", json={"truncated": "maybe"}).status_code == 422
