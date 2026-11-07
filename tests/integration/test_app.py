from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.settings import Settings


def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)))


def test_health_is_ok() -> None:
    response = client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_root_serves_page_with_cqa_app() -> None:
    response = client().get("/")
    assert response.status_code == 200
    assert "<cqa-app" in response.text
