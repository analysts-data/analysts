import copy
import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(encoding="utf-8")
)


class Api:
    """Подменяет /api: GET /api/state отдаёт текущее состояние, решения меняют его, как сервер."""

    def __init__(self, page: Page) -> None:
        self.state: dict[str, Any] = copy.deepcopy(STATE)
        self.posts: list[tuple[str, Any]] = []
        self.errors: list[str] = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.route("**/api/state", lambda route: route.fulfill(json=self.state))
        page.route("**/api/appeals/*/decision", self.decide)

    def decide(self, route: Route) -> None:
        body = route.request.post_data_json
        aid = route.request.url.split("/")[-2]
        self.posts.append((route.request.url, body))
        a = next(x for x in self.state["appeals"] if x["id"] == aid)
        status = "confirmed" if body["to"] == a["from"] else "changed"
        a.update(body, status=status, decidedAt="07.11 16:00")
        route.fulfill(json=a)


def as_reviewer(page: Page, web_url: str, hash_: str) -> None:
    page.goto(f"{web_url}/{hash_}")
    page.locator('[data-act="role"][data-role="reviewer"]').click()


def test_change_decision_previews_new_total_and_posts_new_answer(page: Page, web_url: str) -> None:
    api = Api(page)
    as_reviewer(page, web_url, "#/appeals/a1")
    view = page.locator('[data-view="appeals"]')
    page.get_by_label("Изменить оценку").check()
    page.locator('[data-act="dval"][data-v="20"]').click()
    page.get_by_label("Причина решения, обязательно").fill("Регламент не позволяет называть срок")
    expect(view).to_contain_text("82,94 → 88,82")
    page.locator('[data-act="decide"]').click()
    expect(view).to_contain_text("Оценка изменена")
    assert api.posts == [
        (
            api.posts[0][0],
            {"to": 20, "reason": "Регламент не позволяет называть срок", "reviewer": "Проверяющий"},
        )
    ]
    assert api.posts[0][0].endswith("/api/appeals/a1/decision")
    expect(page.get_by_label("История решений")).to_contain_text("Регламент не позволяет называть срок")
    expect(page.get_by_label("История решений")).to_contain_text("Проверяющий")
    assert api.errors == []


def test_confirm_posts_the_model_answer(page: Page, web_url: str) -> None:
    api = Api(page)
    as_reviewer(page, web_url, "#/appeals/a1")
    page.get_by_label("Подтвердить оценку модели").check()
    page.get_by_label("Причина решения, обязательно").fill("Срок можно было назвать")
    expect(page.locator('[data-view="appeals"]')).to_contain_text("82,94 → 82,94")
    page.locator('[data-act="decide"]').click()
    expect(page.locator('[data-view="appeals"]')).to_contain_text("Оценка подтверждена")
    assert api.posts[0][1]["to"] == 15


def test_decide_is_disabled_until_reason_has_five_characters(page: Page, web_url: str) -> None:
    Api(page)
    as_reviewer(page, web_url, "#/appeals/a1")
    decide = page.locator('[data-act="decide"]')
    expect(decide).to_be_disabled()
    reason = page.get_by_label("Причина решения, обязательно")
    reason.fill("   ок ")
    expect(decide).to_be_disabled()
    reason.fill("Верно")
    expect(decide).to_be_enabled()


def test_closed_appeal_is_decided_without_decision_controls(page: Page, web_url: str) -> None:
    api = Api(page)
    as_reviewer(page, web_url, "#/appeals/a2")
    queue = page.get_by_label("Очередь апелляций")
    expect(queue.locator('a[href="#/appeals/a2"]')).to_contain_text("закрыта")
    expect(page.get_by_label("Рассмотрение")).to_contain_text("Закрыта")
    expect(page.locator('[data-act="decide"]')).to_have_count(0)
    expect(page.get_by_label("Изменить оценку")).to_have_count(0)
    assert api.errors == []
