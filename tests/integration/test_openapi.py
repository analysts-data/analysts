"""OpenAPI /api/openapi.json: every path in a section with a summary, errors with examples, snapshot."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cqa.http.app import create_app
from cqa.http.openapi import DOCS, snapshot
from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    response = TestClient(create_app(Settings(_env_file=None, db_path=":memory:"))).get("/api/openapi.json")
    assert response.status_code == 200
    return response.json()


def _ops(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{m.upper()} {p}": o for p, ops in spec["paths"].items() for m, o in ops.items()}


def test_every_path_has_a_section_summary_and_description(spec: dict[str, Any]) -> None:
    sections = {t["name"] for t in spec["tags"]}
    assert len(sections) == 8
    bare = [
        k
        for k, o in _ops(spec).items()
        if not (set(o.get("tags", [])) & sections and o.get("summary") and o.get("description"))
    ]
    assert not bare, f"добавьте строки в DOCS (src/cqa/http/openapi.py) и запустите make openapi: {bare}"


def test_every_table_row_names_an_existing_path(spec: dict[str, Any]) -> None:
    assert not set(DOCS) - set(_ops(spec)), "строка DOCS для пути, которого нет"


def test_every_error_response_has_an_example_and_validation_errors_name_the_field(
    spec: dict[str, Any],
) -> None:
    for key, operation in _ops(spec).items():
        for code, response in operation["responses"].items():
            if int(code) >= 400:
                assert response["content"]["application/json"]["examples"], f"{key} {code}"
    evaluate = _ops(spec)["POST /api/evaluate"]["responses"]
    assert {"401", "409", "422", "503"} <= set(evaluate)
    field = evaluate["422"]["content"]["application/json"]["examples"]["field"]["value"]["errors"][0]
    assert set(field) == {"path", "message", "expected"}


def test_integration_bodies_carry_examples(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    assert (
        schemas["RecordIn"]["examples"] and schemas["TextIn"]["examples"] and schemas["BatchIn"]["examples"]
    )
    assert (
        "Idempotency-Key"
        in json.dumps(_ops(spec)["POST /api/evaluate"]["parameters"], ensure_ascii=False).title()
    )


def test_committed_snapshot_is_up_to_date() -> None:
    committed = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")
    assert committed == snapshot(), "docs/openapi.json устарел: запустите make openapi"
