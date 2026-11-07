import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)


def serve_state(page: Page) -> None:
    page.route(
        "**/api/state", lambda route: route.fulfill(status=200, content_type="application/json", body=STATE)
    )


def test_mode_banner_and_badges_come_from_state(page: Page, web_url: str) -> None:
    serve_state(page)
    page.goto(f"{web_url}/#/queue")
    mode = page.locator("#mode")
    expect(mode).to_contain_text("Казахстан")
    expect(mode).to_contain_text("обезличены")
    expect(mode).to_contain_text("qwen3-6")
    expect(mode).not_to_contain_text("второе мнение")
    expect(page.locator("#bQueue")).to_have_text("7")
    expect(page.locator("#bAppeals")).to_have_text("1")


def test_mode_banner_says_answers_are_recorded_in_replay(page: Page, web_url: str) -> None:
    serve_state(page)
    page.route(
        "**/api/config",
        lambda r: r.fulfill(status=200, content_type="application/json", body='{"llm_mode": "replay"}'),
    )
    page.goto(f"{web_url}/#/queue")
    mode = page.locator("#mode")
    expect(mode).to_contain_text("Записанные ответы")
    expect(mode).not_to_contain_text("qwen3-6")


def test_state_error_is_shown_on_the_page(page: Page, web_url: str) -> None:
    page.route("**/api/state", lambda route: route.fulfill(status=500, body='{"detail": "база недоступна"}'))
    page.goto(f"{web_url}/#/queue")
    expect(page.locator('[role="alert"]')).to_contain_text("база недоступна")


def test_dataset_by_group_id_posts_and_reports_counts(page: Page, web_url: str) -> None:
    serve_state(page)
    posted: list[dict[str, object]] = []

    def datasets(route: Route) -> None:
        posted.append(json.loads(route.request.post_data or "null"))
        route.fulfill(status=200, content_type="application/json", body='{"added": 12, "skipped": 2}')

    page.route("**/api/datasets", datasets)
    page.goto(f"{web_url}/#/queue")
    page.fill("#gid", "CTRL")
    page.click('[data-act="load"]')
    expect(page.locator("#toast")).to_contain_text("12")
    expect(page.locator("#toast")).to_contain_text("2")
    assert posted == [{"group_id": "CTRL"}]


def test_run_filtered_dialogs_then_stop(page: Page, web_url: str) -> None:
    serve_state(page)
    runs: list[object] = []
    calls: list[str] = []
    status = {"value": "running"}

    def post_run(route: Route) -> None:
        runs.append(json.loads(route.request.post_data or "null"))
        route.fulfill(status=200, content_type="application/json", body='{"run_id": "r1"}')

    def get_run(route: Route) -> None:
        calls.append("get")
        body = {
            "done": 0,
            "total": 1,
            "cost": 0.0,
            "calls": 3,
            "eta_s": 20,
            "errors": [],
            "status": status["value"],
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def cancel(route: Route) -> None:
        calls.append("cancel")
        status["value"] = "cancelled"
        route.fulfill(status=200, content_type="application/json", body='{"status": "cancelled"}')

    page.route("**/api/runs", post_run)
    page.route("**/api/runs/r1", get_run)
    page.route("**/api/runs/r1/cancel", cancel)
    page.goto(f"{web_url}/#/queue?ch=call")
    page.click('[data-act="run"]')
    expect(page.locator("#runProgress")).to_contain_text("оценено 0 из 1 ответов по критериям")
    page.click('[data-act="stop"]')
    expect(page.locator('[data-act="stop"]')).to_have_count(0)
    assert runs == [{"dialogs": ["call-024"], "criteria": None}]
    assert "cancel" in calls
    polls = calls.count("get")
    page.wait_for_timeout(1500)
    assert calls.count("get") == polls
