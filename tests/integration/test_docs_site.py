import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.http.docs import to_html
from cqa.settings import Settings

PAGES = [
    "overview",
    "quickstart",
    "qa-specialist",
    "operator",
    "reviewer",
    "manager",
    "checklist",
    "intonation",
    "rules",
    "integration",
    "api",
    "dynamics",
    "security",
    "control-hour",
    "faq",
    "runbook",
]
EXTERNAL = re.compile(
    r"""(?:src|href|action)\s*=\s*["']?\s*(?:https?:)?//|url\(\s*["']?(?:https?:)?//""", re.I
)


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app(Settings(_env_file=None, db_path=":memory:"))


@pytest.fixture(scope="module")
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("slug", ["", *PAGES])
def test_every_docs_page_is_html_with_navigation(client: TestClient, slug: str) -> None:
    response = client.get(f"/docs/{slug}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert all(f'href="{p}"' in response.text for p in PAGES)


@pytest.mark.parametrize("slug", ["", *PAGES])
def test_docs_pages_load_nothing_from_other_hosts(client: TestClient, slug: str) -> None:
    assert EXTERNAL.findall(client.get(f"/docs/{slug}").text) == []


def test_api_reference_lists_every_openapi_path(app: FastAPI, client: TestClient) -> None:
    html = client.get("/docs/api").text
    paths = app.openapi()["paths"]
    missing = [
        f"{m.upper()} {p}"
        for p, ops in paths.items()
        for m in ops
        if f"{m.upper()}</span> <code>{p}" not in html
    ]
    assert missing == []


def test_markdown_raw_html_is_escaped() -> None:
    html = to_html('<script>alert("x")</script>\n\nтекст <img src=x onerror=alert(1)>')
    assert "<script" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
