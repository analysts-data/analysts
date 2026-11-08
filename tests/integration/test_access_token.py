"""Доступ по токену для показа по сети: CQA_ACCESS_TOKEN, cookie cqa_access, вход /login?token=."""

import logging

import pytest
from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.settings import Settings

TOKEN = "s3cret-token_42"


def client(token: str | None = TOKEN) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, db_path=":memory:", access_token=token)))


def test_without_token_setting_everything_is_open() -> None:
    open_client = client(None)
    assert open_client.get("/api/state").status_code == 200
    assert "<cqa-app" in open_client.get("/").text


def test_empty_token_env_keeps_the_app_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CQA_ACCESS_TOKEN", "")
    assert Settings(_env_file=None).access_token is None


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_api_without_cookie_is_401_json(method: str) -> None:
    response = client().request(method, "/api/config", json={})
    assert response.status_code == 401
    assert "detail" in response.json()


def test_ui_without_cookie_is_access_page_without_data() -> None:
    response = client().get("/")
    assert response.status_code == 401
    assert "Доступ по ссылке с токеном" in response.text
    assert "<cqa-app" not in response.text


def test_health_stays_open() -> None:
    assert client().get("/api/health").json() == {"ok": True}


def test_login_sets_http_only_lax_cookie_and_redirects_home() -> None:
    response = client().get(f"/login?token={TOKEN}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert "cqa_access=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_cookie_from_login_opens_api_and_ui() -> None:
    browser = client()
    browser.get(f"/login?token={TOKEN}")
    assert browser.get("/api/state").status_code == 200
    assert "<cqa-app" in browser.get("/").text


def test_wrong_token_or_cookie_is_401() -> None:
    browser = client()
    response = browser.get("/login?token=wrong", follow_redirects=False)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert "Доступ по ссылке с токеном" in response.text
    browser.cookies.set("cqa_access", "wrong")
    assert browser.get("/api/state").status_code == 401
    browser.cookies.clear()
    not_ascii = {"cookie": "cqa_access=токен".encode()}  # still a 401, not a 500
    assert browser.get("/api/state", headers=not_ascii).status_code == 401


def test_token_is_never_in_denied_responses() -> None:
    for path in ("/", "/api/state", "/login?token=wrong", "/app.js"):
        response = client().get(path)
        assert TOKEN not in response.text
        assert TOKEN not in str(response.headers)


def test_access_log_hides_the_login_token(caplog: pytest.LogCaptureFixture) -> None:
    client()
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "10.0.0.7:5000", "GET", f"/login?token={TOKEN}", "1.1", 302
        )
    assert TOKEN not in caplog.text
    assert "/login?token=***" in caplog.text
