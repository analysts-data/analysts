import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "analytics_state.json").read_text(encoding="utf-8")

EMPLOYEES = [
    {"id": "e1", "name": "Алия К.", "role": "operator", "team": "Поддержка RU", "active": True},
    {"id": "e2", "name": "Борис П.", "role": "reviewer", "team": "Контроль качества", "active": True},
    {"id": "e3", "name": "Вера С.", "role": "operator", "team": "Поддержка RU", "active": False},
]
OVERVIEW = {
    "at": "2026-11-08T07:00:00+05:00",
    "employees": [
        {**EMPLOYEES[0], "today": {"appeal.file": 2}, "week": {"appeal.file": 3, "dialog.reviewed": 1}, "appeals_filed": 3, "decisions": 0, "manual_answers": 0, "checklist_saves": 0, "dialogs_reviewed": 1, "median_decision_min": None},
        {**EMPLOYEES[1], "today": {"appeal.decide": 1}, "week": {"appeal.decide": 4}, "appeals_filed": 0, "decisions": 4, "manual_answers": 2, "checklist_saves": 1, "dialogs_reviewed": 0, "median_decision_min": 95.0},
        {**EMPLOYEES[2], "today": {}, "week": {}, "appeals_filed": 0, "decisions": 0, "manual_answers": 0, "checklist_saves": 0, "dialogs_reviewed": 0, "median_decision_min": None},
    ],
    "teams": [
        {"team": "Контроль качества", "employees": 1, "today": 1, "week": 4},
        {"team": "Поддержка RU", "employees": 2, "today": 2, "week": 4},
    ],
    "unattributed": {"today": 1, "week": 5},
    "workload": {"pending_appeals": 2, "needs_review": 3, "unreviewed": 9},
}
ALIYA = {
    "operator": "Алия К.",
    "dialogs": 7,
    "n": 6,
    "avg_total": 72.5,
    "sd": 8.1,
    "ci95": [64.0, 81.0],
    "ranked": True,
    "reason": None,
    "gross_errors": 1,
    "needs_review": 2,
    "appeals_open": 1,
    "weakest": [{"cid": "07", "name": "Завершение", "share": 0.33}],
    "trend": [{"day": "07.11", "avg_total": 70.0, "dialogs": 1}, {"day": "08.11", "avg_total": 73.75, "dialogs": 2}],
    "dialog_ids": ["call-024", "p1-kz-015"],
    "reasons": [{"tag": "Не назван срок ответа", "dialogs": 2, "owner": "Сервис", "criteria": ["04"]}],
}
ROW = {k: v for k, v in ALIYA.items() if k not in ("dialog_ids", "reasons")}
UNKNOWN = {**ROW, "operator": "Не указан", "n": 2, "sd": None, "ranked": False, "reason": "сотрудник не указан", "gross_errors": 0, "weakest": []}
# новый контракт: {definitions, min_n, operators}; сервер ставит «кому нужна помощь» первыми, экран показывает по алфавиту
OPERATORS = {"definitions": {"sd": "стандартное отклонение итога"}, "min_n": 5, "operators": [UNKNOWN, ROW]}
REPORT = {"operators": {"attention": [ROW], "strengths": []}}


def stub(page: Page, path: str, body: Any) -> None:
    page.route(re.compile(rf".*/api{re.escape(path)}(\?.*)?$"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body)))


def open_people(page: Page, web_url: str, route: str) -> tuple[list[str], list[str]]:
    """Ответы по контракту на пути «Сотрудников»; возвращает (ошибки консоли и ответы 4xx, запросы к /api/)."""
    problems: list[str] = []
    requests: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.on("request", lambda r: requests.append(f"{r.method} {r.url.split('/api', 1)[1]}") if "/api/" in r.url else None)
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    stub(page, "/employees", EMPLOYEES)
    stub(page, "/overview", OVERVIEW)
    stub(page, "/operators", OPERATORS)
    stub(page, "/operators/%D0%90%D0%BB%D0%B8%D1%8F%20%D0%9A.", ALIYA)
    stub(page, "/operators/%D0%9D%D0%B5%20%D1%83%D0%BA%D0%B0%D0%B7%D0%B0%D0%BD", {**UNKNOWN, "dialog_ids": [], "reasons": [], "min_n": 5})
    stub(page, "/report", REPORT)
    page.goto(f"{web_url}/{route}")
    expect(page.locator('[data-view="people"] h1')).to_be_visible()
    return problems, requests


def test_overview_shows_open_workload_people_by_team_and_operator_scores(page: Page, web_url: str) -> None:
    problems, _ = open_people(page, web_url, "#/people")
    load = page.locator('[aria-label="Открытая нагрузка"]')
    expect(load.locator("strong")).to_have_text(["2", "3", "9"])
    expect(load.locator('a[href="#/appeals"]')).to_contain_text("апелляций ждут решения")
    work = page.locator('[aria-label="Работа сотрудников"]')
    expect(work.locator("tr.grp")).to_have_text([re.compile("^Контроль качества"), re.compile("^Поддержка RU")])
    row = work.locator('tr[data-id="e1"]')
    expect(row.locator("td")).to_have_text(["Алия К.", "Оператор", "2", "4", "3", "0", "—", "0", "0", "1"])
    expect(work.locator('tr[data-id="e2"] td').nth(6)).to_have_text("1,6 ч")
    expect(work.locator('tr[data-id="e3"]')).to_contain_text("не работает")
    expect(work).to_contain_text("Действия без входа: сегодня 1, за 7 дней 5")
    attention = page.locator('[aria-label="Требуют внимания"] li')
    expect(attention).to_have_count(1)
    expect(attention.first).to_contain_text("Алия К.72,50 ± 8,1 (n=6)грубых ошибок: 1")
    expect(page.locator('[aria-label="Сильные стороны"]')).to_contain_text("Пока некого показать")
    ops = page.locator('[aria-label="Оценки по операторам"] tbody tr')
    expect(ops).to_have_count(2)
    expect(ops.first.locator("td").nth(2)).to_have_text("72,50 ± 8,1 (n=6)")  # по алфавиту, не рейтинг
    expect(ops.nth(1).locator("td").nth(2)).to_have_text("недостаточно данных (n=2)")
    expect(ops.first).to_contain_text("07 Завершение 33%")
    expect(ops.first.locator("a")).to_have_attribute("href", "#/people/e1")
    row.click()
    expect(page).to_have_url(re.compile(r"#/people/e1$"))
    expect(page.locator('[data-view="people"] h1')).to_have_text("Алия К.")
    assert problems == []


def test_employee_page_shows_total_gross_weak_criteria_trend_and_activity(page: Page, web_url: str) -> None:
    problems, requests = open_people(page, web_url, "#/people/e1")
    expect(page.locator('[data-view="people"] h1')).to_have_text("Алия К.")
    expect(page.locator('[aria-label="Оценки"] strong')).to_have_text(["72,50", "1", "2", "1"])
    expect(page.locator('[aria-label="Оценки"]')).to_contain_text("± 8,1, n=6 из 7 диалогов")
    expect(page.locator('[aria-label="Оценки"]')).to_contain_text("интервал 64–81")
    expect(page.locator('[aria-label="Требуют внимания"] a[href="#/queue?lost=07"]')).to_contain_text("Завершение")
    trend = page.locator('[aria-label="Тренд по дням"]')
    expect(trend.locator("li")).to_have_text(["07.11 (1): 70,00", "08.11 (2): 73,75"])
    expect(page.locator('[aria-label="Диалоги сотрудника"] a[href="#/d/call-024"]')).to_be_visible()
    expect(page.locator('[aria-label="Причины снижения"]')).to_contain_text("Не назван срок ответа")
    acts = page.locator('[aria-label="Действия"] tbody tr')
    expect(acts.first.locator("td")).to_have_text(["Подал апелляцию", "2", "3"])
    expect(page.locator('a[href="#/audit?actor=e1"]')).to_contain_text("Журнал действий")
    assert "GET /operators/%D0%90%D0%BB%D0%B8%D1%8F%20%D0%9A." in requests
    assert problems == []


def test_operator_with_few_dialogs_shows_insufficient_data_instead_of_score(page: Page, web_url: str) -> None:
    problems, _ = open_people(page, web_url, "#/people/%D0%9D%D0%B5%20%D1%83%D0%BA%D0%B0%D0%B7%D0%B0%D0%BD")
    scores = page.locator('[aria-label="Оценки"]')
    expect(scores.locator("strong").first).to_have_text("недостаточно данных")
    expect(scores).to_contain_text("сотрудник не указан")
    assert problems == []


def test_reviewer_page_skips_scores_request(page: Page, web_url: str) -> None:
    problems, requests = open_people(page, web_url, "#/people/e2")
    expect(page.locator('[aria-label="Действия"] tbody tr').first).to_contain_text("Решил апелляцию")
    expect(page.locator('[data-view="people"]')).to_contain_text("Медиана от апелляции до решения: 95 мин")
    assert not [r for r in requests if r.startswith("GET /operators/")]
    assert problems == []


def test_import_checks_rows_before_sending_and_posts_raw_csv(page: Page, web_url: str) -> None:
    bodies: list[str] = []

    def imported(route: Route) -> None:
        bodies.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json", body='{"added": 1, "updated": 1}')

    open_people(page, web_url, "#/people")
    page.route("**/api/employees/import", imported)
    page.click('[data-act="import"]')
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading")).to_have_text("Импортировать CSV")
    send = dialog.locator('[data-act="import-send"]')
    expect(send).to_be_disabled()
    area = dialog.get_by_label("Или вставьте строки")
    area.fill("id;name;role;team\ne4;Гульнар;boss;RU")
    expect(dialog.get_by_role("alert")).to_have_text(re.compile("Строка 2: роль «boss» неизвестна"))
    expect(send).to_be_disabled()
    page.keyboard.press("Escape")
    page.click('[data-act="import"]')
    expect(area).to_have_value("id;name;role;team\ne4;Гульнар;boss;RU")  # черновик не потерян
    area.fill("id;name;role;team\ne4;Гульнар;qa;RU\ne1;Алия К.;operator;Поддержка RU")
    send.click()
    expect(page.locator("#toast")).to_contain_text("добавлено 1, обновлено 1")
    assert bodies == ["id;name;role;team\ne4;Гульнар;qa;RU\ne1;Алия К.;operator;Поддержка RU"]


def test_operator_import_reports_unknown_dialogs(page: Page, web_url: str) -> None:
    open_people(page, web_url, "#/people")
    page.route(
        "**/api/operators/import",
        lambda r: r.fulfill(status=200, content_type="application/json", body='{"updated": 1, "unknown_ids": ["x-9"]}'),
    )
    page.click('[data-act="import"]')
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Операторы диалогов").check()
    dialog.get_by_label("Или вставьте строки").fill("call-024;Алия К.\nx-9;Борис П.")
    dialog.locator('[data-act="import-send"]').click()
    expect(page.locator("#toast")).to_contain_text("Операторы назначены: 1 диалогов; не найдены: x-9")


@pytest.mark.parametrize("route", ["#/people", "#/people/e1"])
def test_people_fit_390px(page: Page, web_url: str, route: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    problems, _ = open_people(page, web_url, route)
    page.wait_for_load_state("networkidle")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert problems == []
