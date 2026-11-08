"""Отчёты по замерам: каталог, качество оценки, отчёт запуска, файлы результатов. Данные синтетические."""

import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import MODEL_REASON as REASON
from fakes import FakeEvaluator, FakeSource
from fakes import eval_report_body as eval_body


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "eval-reports", tmp_path / "results"


@pytest.fixture
def api(
    dirs: tuple[Path, Path], store: Store, conn: sqlite3.Connection, evaluator: FakeEvaluator
) -> Iterator[TestClient]:
    reports, results = dirs
    settings = Settings(_env_file=None, db_path=":memory:", eval_reports_dir=reports, results_dir=results)
    with TestClient(create_app(settings, source=FakeSource(), evaluator=evaluator, conn=conn)) as client:
        yield client


def put(directory: Path, name: str, body: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def test_quality_list_is_empty_without_eval_reports(api: TestClient) -> None:
    assert api.get("/api/quality").json() == []


def test_quality_list_is_newest_first_and_skips_other_files(api: TestClient, dirs: tuple[Path, Path]) -> None:
    put(dirs[0], "20261107T100000Z.json", eval_body(problems=[]))
    put(dirs[0], "20261108T010203Z.json", eval_body(agree_total=0.8))
    put(dirs[0], "holdout-20261108T020000Z.json", {"rows": [], "n": 0, "hits": 0, "problems": []})
    put(dirs[0], "20261108T030000Z.json", "{broken")

    runs = api.get("/api/quality").json()

    assert runs == [
        {
            "id": "20261108T010203Z",
            "created": "2026-11-08T01:02:03Z",
            "model": "model-x",
            "n_dialogs": 4,
            "agree_total": 0.8,
            "passed": False,
        },
        {
            "id": "20261107T100000Z",
            "created": "2026-11-07T10:00:00Z",
            "model": "model-x",
            "n_dialogs": 4,
            "agree_total": 0.9,
            "passed": True,
        },
    ]


def test_quality_report_json_keeps_model_reasons_and_threshold_checks(
    api: TestClient, dirs: tuple[Path, Path]
) -> None:
    put(dirs[0], "20261108T010203Z.json", eval_body())

    body = api.get("/api/quality/20261108T010203Z?format=json").json()

    assert body["id"] == "20261108T010203Z" and body["agree_total"] == 0.9
    assert body["disagreements"][0]["why"] == REASON
    assert {c["name"] for c in body["thresholds"]} >= {"stability_min", "gross_recall_min"}


@pytest.mark.parametrize(
    ("fmt", "media", "start"),
    [
        ("html", "text/html; charset=utf-8", "<!doctype html>"),
        ("md", "text/markdown; charset=utf-8", "# "),
        ("csv", "text/csv; charset=utf-8", "﻿"),
    ],
)
def test_quality_report_printable_formats_have_no_dialogue_text(
    api: TestClient, dirs: tuple[Path, Path], fmt: str, media: str, start: str
) -> None:
    put(dirs[0], "20261108T010203Z.json", eval_body())

    response = api.get(f"/api/quality/20261108T010203Z?format={fmt}")

    assert response.headers["content-type"] == media
    assert response.text.startswith(start)
    assert "dlg-1" in response.text and REASON not in response.text


def test_unknown_quality_report_is_404(api: TestClient, dirs: tuple[Path, Path]) -> None:
    put(dirs[0], "20261108T010203Z.json", eval_body())

    assert api.get("/api/quality/20261101T000000Z").status_code == 404
    assert api.get("/api/quality/..%2Fsecret").status_code == 404
    assert api.get("/api/quality/20261108T010203Z?format=pdf").status_code == 422


def _finished(client: TestClient, run_id: int) -> None:
    deadline = time.monotonic() + 2
    while client.get(f"/api/runs/{run_id}").json()["status"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_run_report_has_progress_and_answer_distribution(api: TestClient) -> None:
    run_id = api.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"]
    _finished(api, run_id)

    body = api.get(f"/api/runs/{run_id}/report?format=json").json()
    page = api.get(f"/api/runs/{run_id}/report?format=html")

    assert (body["done"], body["total"], body["status"], body["progress"]) == (16, 16, "done", 1.0)
    assert body["checklist_versions"] == [3]
    assert len(body["criteria"]) == 8 and all(c["n"] == 2 for c in body["criteria"])
    assert page.headers["content-type"] == "text/html; charset=utf-8"
    assert "Ответы по критериям" in page.text
    assert api.get("/api/runs/999/report").status_code == 404


def test_catalogue_lists_offered_reports_with_routes_that_exist(
    api: TestClient, dirs: tuple[Path, Path]
) -> None:
    put(dirs[1] / "dev", "results.json", {"version": "1.0"})
    put(dirs[0], "20261108T010203Z.json", eval_body())
    run_id = api.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"]
    _finished(api, run_id)
    item = {"quality": "20261108T010203Z", "run": str(run_id)}

    reports = api.get("/api/reports").json()
    ids = [r["id"] for r in reports]

    assert {"executive", "quality", "run", "checklist", "checklist-diff", "results-dev"} <= set(ids)
    assert "results-prod" not in ids
    for r in reports:
        assert set(r) >= {"id", "title", "description", "formats", "href_template"}
        for fmt in r["formats"]:
            href = r["href_template"].format(format=fmt, id=item.get(r["id"], ""), **{"from": "3"})
            assert api.get(href).status_code == 200, href


def test_results_file_is_downloaded_when_it_exists(api: TestClient, dirs: tuple[Path, Path]) -> None:
    put(dirs[1] / "dev", "results.json", {"version": "1.0"})

    response = api.get("/api/results/dev")

    assert response.json() == {"version": "1.0"}
    assert 'filename="results-dev.json"' in response.headers["content-disposition"]
    assert api.get("/api/results/prod").status_code == 404
    assert api.get("/api/results/other").status_code == 422


def test_executive_report_is_also_a_csv(api: TestClient) -> None:
    response = api.get("/api/report?format=csv")

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.text.startswith("﻿")
