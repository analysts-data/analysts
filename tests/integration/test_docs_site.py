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


def test_unknown_docs_page_is_404(client: TestClient) -> None:
    assert client.get("/docs/no-such-page").status_code == 404


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


def test_every_api_operation_has_a_russian_summary(app: FastAPI) -> None:
    ops = [(p, m, op) for p, item in app.openapi()["paths"].items() for m, op in item.items()]
    english = [f"{m.upper()} {p}" for p, m, op in ops if not re.search("[а-яё]", op.get("summary", ""), re.I)]
    assert english == []


def test_markdown_raw_html_is_escaped() -> None:
    html = to_html('<script>alert("x")</script>\n\nтекст <img src=x onerror=alert(1)>')
    assert "<script" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


def test_search_index_has_a_section_of_every_page(client: TestClient) -> None:
    index = client.get("/docs/search.json").json()
    assert {entry["url"].split("#")[0] for entry in index} == set(PAGES)
    markup = re.compile(r"</?(?:p|a|code|pre|h[1-6]|li|ul|ol|table|tr|td|th|strong|em|span)\b")
    assert all(entry["title"] and not markup.search(entry["text"]) for entry in index)


def test_fastapi_swagger_and_redoc_are_off_and_schema_moved_under_api(client: TestClient) -> None:
    assert "swagger" not in client.get("/docs").text.lower()
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert "/api/state" in client.get("/api/openapi.json").json()["paths"]
