import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)
CATALOG = [
    {
        "id": "executive",
        "title": "Отчёт для руководства",
        "description": "Сводка на одной странице.",
        "formats": ["html", "md"],
        "href_template": "/api/report?format={format}",
    },
    {
        "id": "run",
        "title": "Отчёт запуска оценки",
        "description": "Ответы запуска по критериям.",
        "formats": ["html", "csv"],
        "href_template": "/api/runs/{id}/report?format={format}",
        "items": "/api/runs",
    },
    {
        "id": "checklist-diff",
        "title": "Изменения чек-листа",
        "description": "Разница с текущей версией.",
        "formats": ["md"],
        "href_template": "/api/checklist/diff?from={from}&format={format}",
    },
]
RUNS = [
    {"id": 4, "created": "2026-11-08T06:30:00+05:00", "status": "done", "model": "qwen3-6"},
    {"id": 3, "created": "2026-11-08T05:10:00+05:00", "status": "done", "model": "jev"},
]


def watch(page: Page) -> list[str]:
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    return problems


def test_catalog_fills_templates_with_format_item_and_version(page: Page, web_url: str) -> None:
    problems = watch(page)
    downloads: list[str] = []

    def file(route: Route) -> None:
        downloads.append(route.request.url.split("/api", 1)[1])
        route.fulfill(
            status=200,
            content_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="run-3.csv"'},
            body="﻿a;b\n",
        )

    page.route(
        "**/api/reports",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG)),
    )
    page.route(
        "**/api/runs", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(RUNS))
    )
    page.route(re.compile(r".*/api/runs/\d+/report\?format=csv$"), file)
    page.goto(f"{web_url}/#/reports")
    expect(page.locator('[data-view="reports"] h1')).to_have_text("Отчёты")
    exe = page.locator('[data-report="executive"]')
    expect(exe.get_by_role("link", name="Открыть")).to_have_attribute("href", "/api/report?format=html")
    expect(exe.get_by_role("button", name="Markdown")).to_be_visible()

    run = page.locator('[data-report="run"]')
    expect(run.get_by_role("link", name="Открыть")).to_have_attribute(
        "href", "/api/runs/4/report?format=html"
    )
    run.get_by_label("Прогон").select_option("3")
    expect(run.get_by_role("link", name="Открыть")).to_have_attribute(
        "href", "/api/runs/3/report?format=html"
    )
    with page.expect_download() as dl:
        run.get_by_role("button", name="CSV").click()
    assert dl.value.suggested_filename == "run-3.csv"
    assert downloads == ["/runs/3/report?format=csv"]

    diff = page.locator('[data-report="checklist-diff"]')
    expect(diff.get_by_label("С версии")).to_have_value("2")
    assert problems == []


def test_export_button_says_file_is_being_prepared(page: Page, web_url: str) -> None:
    watch(page)
    pending: list[Route] = []
    page.route(
        "**/api/reports",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG[:1])),
    )
    page.route("**/api/report?format=md", lambda r: pending.append(r))
    page.goto(f"{web_url}/#/reports")
    button = page.locator('[data-report="executive"] [data-act="download"]')
    button.click()
    expect(button).to_have_text("Готовится файл…")
    expect(button).to_be_disabled()
    while not pending:
        page.wait_for_timeout(50)
    with page.expect_download():
        pending[0].fulfill(status=200, content_type="text/markdown", body="# Отчёт")
    expect(button).to_have_text("Markdown")
    expect(button).to_be_enabled()


def test_server_without_catalog_shows_main_reports(page: Page, web_url: str) -> None:
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route(
        "**/api/reports",
        lambda r: r.fulfill(status=404, content_type="application/json", body='{"detail": "Not Found"}'),
    )
    page.goto(f"{web_url}/#/reports")
    expect(page.locator('[data-view="reports"]')).to_contain_text("показаны основные отчёты")
    expect(page.locator('[data-report="executive"] a')).to_have_attribute("href", "/api/report?format=html")
    expect(page.locator('[data-report="scores"]')).to_contain_text("Оценки по диалогам")


def test_reports_fit_390px(page: Page, web_url: str) -> None:
    problems = watch(page)
    page.route(
        "**/api/reports",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG)),
    )
    page.route(
        "**/api/runs", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(RUNS))
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{web_url}/#/reports")
    expect(page.locator('[data-report="run"]')).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
