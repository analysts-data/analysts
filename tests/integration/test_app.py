import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.services.errors import Conflict, Invalid, NotFound, Unavailable, Upstream
from cqa.settings import Settings


def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, db_path=":memory:")))


def test_health_is_ok() -> None:
    response = client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_root_serves_page_with_cqa_app() -> None:
    response = client().get("/")
    assert response.status_code == 200
    assert "<cqa-app" in response.text


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (NotFound("Диалог d не найден"), 404),
        (Invalid("Пустая причина в апелляции a1"), 422),
        (Conflict("Запуск 1 ещё идёт"), 409),
        (Upstream("API организаторов не ответил"), 502),
        (Unavailable("Оценщик не подключён"), 503),
    ],
)
def test_service_error_becomes_http_response(exc: Exception, code: int) -> None:
    app = create_app(Settings(_env_file=None, db_path=":memory:"))

    def boom() -> None:
        raise exc

    app.router.routes.insert(0, APIRoute("/boom", boom))  # before the static mount on "/"
    response = TestClient(app).get("/boom")
    assert response.status_code == code
    assert response.json() == {"detail": str(exc)}
