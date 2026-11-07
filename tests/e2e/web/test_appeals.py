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
        page.route("**/api/appeals", self.appeal)
        page.route("**/api/dialogs/*/reviewed", self.reviewed)

    def reviewed(self, route: Route) -> None:
        body = route.request.post_data_json
        did = route.request.url.split("/")[-2]
        self.posts.append((route.request.url, body))
        next(d for d in self.state["dialogs"] if d["id"] == did)["reviewed"] = body["reviewed"]
        route.fulfill(json={"ok": True})

    def appeal(self, route: Route) -> None:
        body = route.request.post_data_json
        self.posts.append((route.request.url, body))
        a = {
            **body,
            "id": "a9",
            "kind": "appeal",
            "from": 5,
            "to": None,
            "at": "07.11 16:00",
            "status": "pending",
            "reviewer": None,
            "reason": None,
            "decidedAt": None,
        }
        self.state["appeals"].append(a)
        route.fulfill(json=a)

    def decide(self, route: Route) -> None:
        body = route.request.post_data_json
        aid = route.request.url.split("/")[-2]
        self.posts.append((route.request.url, body))
        a = next(x for x in self.state["appeals"] if x["id"] == aid)
        status = "confirmed" if body["to"] == a["from"] else "changed"
        a.update(body, status=status, decidedAt="07.11 16:00")
        route.fulfill(json=a)


def open_criterion(page: Page, cid: str) -> None:
    row = page.locator(f'.crit[data-cid="{cid}"] .crit-row')
    if row.get_attribute("aria-expanded") != "true":
        row.click()


def test_appeal_from_card_posts_answer_comment_and_line(page: Page, web_url: str) -> None:
    api = Api(page)
    page.goto(f"{web_url}/#/d/p1-ru-003")
    open_criterion(page, "04")
    page.locator('[data-act="appeal"][data-cid="04"]').click()
    form = page.locator("#dlg")
    expect(form).to_be_visible()
    expect(form.get_by_label("Критерий")).to_have_value("04")
    form.get_by_label("Какой ответ вы считаете верным").select_option("10")
    send = form.get_by_role("button", name="Отправить апелляцию")
    comment = form.get_by_label("Комментарий, обязательно")
    comment.fill("Коротко   ")
    expect(send).to_be_disabled()
    comment.fill("Срок вывода назван, это существенная часть ответа.")
    expect(send).to_be_enabled()
    form.get_by_label("Реплика в подтверждение").select_option("8")
    send.click()
    expect(form).to_be_hidden()
    expect(page.locator("#toast")).to_contain_text("отправлена")
    expect(page.locator('.crit[data-cid="04"]')).to_contain_text("Апелляция на рассмотрении")
    assert api.posts == [
        (
            api.posts[0][0],
            {
                "dlg": "p1-ru-003",
                "cid": "04",
                "ask": 10,
                "ev": [8],
                "comment": "Срок вывода назван, это существенная часть ответа.",
                "by": "Специалист КК",
            },
        )
    ]
    assert api.posts[0][0].endswith("/api/appeals")
    assert api.errors == []


def test_appeal_form_offers_only_scored_criteria_and_other_answers(page: Page, web_url: str) -> None:
    Api(page)
    page.goto(f"{web_url}/#/d/call-024")
    open_criterion(page, "06")
    page.locator('[data-act="appeal"][data-cid="06"]').click()
    form = page.locator("#dlg")
    cids = form.get_by_label("Критерий").locator("option").evaluate_all("os => os.map(o => o.value)")
    assert "04" not in cids  # по 04 уже есть апелляция a1 на рассмотрении
    assert "08" not in cids  # флаг не оспаривается
    asks = form.get_by_label("Какой ответ вы считаете верным").locator("option")
    assert asks.evaluate_all("os => os.map(o => o.value)") == ["10", "4", "0"]  # без текущего 7
    form.get_by_label("Критерий").select_option("01")
    assert asks.evaluate_all("os => os.map(o => o.value)") == ["no"]


def test_reviewed_mark_posts_flag_and_takes_dialog_out_of_risk(page: Page, web_url: str) -> None:
    api = Api(page)
    page.goto(f"{web_url}/#/d/p1-ru-022")
    card = page.locator('[data-view="d"]')
    mark = page.locator('[data-act="reviewed"]')
    expect(card).to_contain_text("Грубая ошибка, нужна проверка")
    expect(mark).to_have_text("Отметить проверенным")
    mark.click()
    expect(mark).to_have_text("Снять отметку")
    expect(card).not_to_contain_text("Грубая ошибка, нужна проверка")
    mark.click()
    expect(mark).to_have_text("Отметить проверенным")
    expect(card).to_contain_text("Грубая ошибка, нужна проверка")
    assert [body for _, body in api.posts] == [{"reviewed": True}, {"reviewed": False}]
    assert api.posts[0][0].endswith("/api/dialogs/p1-ru-022/reviewed")
    assert api.errors == []


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
