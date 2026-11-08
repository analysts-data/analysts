"""CORS для встраивания в Dynamics 365: только https://*.dynamics.com, без credentials (задача 10.6)."""

import pytest
from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.settings import Settings


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, db_path=":memory:")))


def preflight(client: TestClient, origin: str, method: str = "GET"):
    return client.options("/api/state", headers={"Origin": origin, "Access-Control-Request-Method": method})


def test_preflight_from_dynamics_tenant_is_allowed(client: TestClient) -> None:
    response = preflight(client, "https://org.crm4.dynamics.com", "PUT")
    assert response.headers["access-control-allow-origin"] == "https://org.crm4.dynamics.com"
    assert "PUT" in response.headers["access-control-allow-methods"]
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_preflight_from_foreign_origin_is_rejected(client: TestClient) -> None:
    response = preflight(client, "https://evil.example")
    assert "access-control-allow-origin" not in response.headers


def test_preflight_allows_the_current_user_header(client: TestClient) -> None:
    headers = {
        "Origin": "https://org.crm4.dynamics.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-cqa-user",
    }
    response = client.options("/api/appeals", headers=headers)
    assert response.status_code == 200
    assert "x-cqa-user" in response.headers["access-control-allow-headers"].lower()
