import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)


RUNNING = {"done": 3, "total": 10, "cost": 0.02, "calls": 3, "eta_s": 40, "errors": [], "status": "running"}


class Api:
    """Перехват API: после PUT /api/checklist состояние меняется, как на сервере."""

    def __init__(self, page: Page, put_reply: dict[str, Any] | None = None) -> None:
        self.state = json.loads(STATE)
        self.put_reply = put_reply
        self.puts: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.cancels = 0
        self.finish = False
        page.route("**/api/state", lambda route: route.fulfill(json=self.state))
        page.route("**/api/checklist", self.on_checklist)
        page.route("**/api/runs", self.on_run)
        page.route("**/api/runs/r9", self.on_poll)
        page.route("**/api/runs/r9/cancel", self.on_cancel)

    def on_checklist(self, route: Route) -> None:
        assert route.request.method == "PUT" and self.put_reply
        draft, v, pending = route.request.post_data_json, self.put_reply["version"], self.put_reply["pending"]
        self.puts.append(draft)
        self.state["checklist"] = {**draft, "version": v}
        self.state["versions"].append({"v": v, "note": f"изменены {', '.join(pending)}"})
        for d in self.state["dialogs"]:
            for cid in pending:
                d["res"].pop(cid, None)
        route.fulfill(json=self.put_reply)

    def on_run(self, route: Route) -> None:
        self.runs.append(route.request.post_data_json)
        route.fulfill(json={"run_id": "r9"})

    def on_poll(self, route: Route) -> None:
        if self.cancels:  # as the server: cancelled once the dialogs in flight are saved
            return route.fulfill(json={**RUNNING, "status": "cancelled"})
        if not self.finish:
            return route.fulfill(json=RUNNING)
        for d in self.state["dialogs"]:  # оценка готова: записи по pending снова есть
            for cid in self.put_reply["pending"] if self.put_reply else []:
                d["res"][cid] = {"a": "na", "why": "Новая оценка."}
        route.fulfill(json={**RUNNING, "done": 10, "cost": 0.07, "calls": 10, "eta_s": 0, "status": "done"})

    def on_cancel(self, route: Route) -> None:
        self.cancels += 1
        route.fulfill(json={"status": "cancelled"})


def open_checklist(page: Page, web_url: str, put_reply: dict[str, Any] | None = None) -> Api:
    api = Api(page, put_reply)
    page.goto(f"{web_url}/#/checklist")
    expect(page.locator('[data-view="checklist"] h1')).to_have_text("Чек-лист качества")
    return api


def item(page: Page, cid: str) -> Locator:
    return page.locator(f'[data-view="checklist"] [data-act="csel"][data-cid="{cid}"]')


def test_weight_change_shows_sum_and_changed_mark_and_reset_restores(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    expect(page.get_by_text("Сумма весов 100")).to_be_visible()
    item(page, "04").click()
    page.locator("#cf-w").fill("25")
    page.locator("#cf-w").press("Tab")
    expect(page.get_by_text("Сумма весов 105")).to_be_visible()
    expect(page.get_by_text("Итог всё равно приводится к 100")).to_be_visible()
    expect(item(page, "04")).to_contain_text("изменён")
    expect(item(page, "03")).not_to_contain_text("изменён")
    page.locator('[data-act="creset"]').click()
    expect(page.get_by_text("Сумма весов 100")).to_be_visible()
    expect(item(page, "04")).not_to_contain_text("изменён")


def test_type_change_rebuilds_fields(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    item(page, "01").click()
    expect(page.locator("#cf-steps")).to_have_count(0)
    page.locator("#cf-type").select_option("scale")
    expect(page.locator("#cf-steps")).to_have_value("10: Полностью\n5: Частично\n0: Нет")
    expect(page.locator("#cf-w")).to_be_visible()
    page.locator("#cf-type").select_option("flag")
    expect(page.locator("#cf-w")).to_have_count(0)
    expect(page.locator("#cf-steps")).to_have_count(0)
    expect(page.locator("#cf-q")).to_be_visible()


def test_add_and_delete_criterion(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    page.locator('[data-act="cadd"]').click()
    expect(item(page, "09")).to_contain_text("изменён")
    expect(page.locator('[data-view="checklist"] legend')).to_contain_text("Критерий 09")
    expect(page.locator("#cf-type")).to_have_value("bool")
    expect(page.locator("#cf-sec")).to_have_value("2")
    expect(page.locator("#cf-w")).to_have_value("5")
    expect(page.locator("#cf-na")).not_to_be_checked()
    expect(page.locator("#cf-ch")).to_have_value("all")
    expect(page.get_by_text("Сумма весов 105")).to_be_visible()
    page.locator('[data-act="cdel"]').click()
    expect(item(page, "09")).to_have_count(0)
    expect(page.get_by_text("Сумма весов 100")).to_be_visible()


TEXT_04 = "Оцените ответ и названный срок по шкале."
TEXT_09 = "Да — оператор назвал срок ответа."


def save_text_change(page: Page) -> None:
    item(page, "04").click()
    page.locator("#cf-text").fill(TEXT_04)
    page.locator("#cf-text").press("Tab")
    page.locator('[data-act="csave"]').click()
    expect(item(page, "04")).to_contain_text("ждёт оценки")


def test_save_applies_new_version_and_marks_pending(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    save_text_change(page)
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 4 применяется")
    expect(page.locator('[data-view="checklist"]')).to_contain_text("v4: изменены 04 применяется")
    expect(item(page, "04")).not_to_contain_text("изменён")
    expect(item(page, "03")).not_to_contain_text("ждёт оценки")
    expect(page.locator('[data-act="csave"]')).to_have_text("Сохранить как v5")
    [draft] = api.puts
    assert draft["version"] == 3
    assert next(c for c in draft["criteria"] if c["id"] == "04")["text"] == TEXT_04


def test_double_click_on_save_sends_one_put(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": []})
    item(page, "06").click()
    page.locator("#cf-w").fill("10")
    page.locator("#cf-w").press("Tab")
    page.locator('[data-act="csave"]').dblclick()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 4 применяется")
    page.wait_for_timeout(300)
    assert len(api.puts) == 1


def test_new_criterion_is_sent_and_waits_for_evaluation(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["09"]})
    page.locator('[data-act="cadd"]').click()
    page.locator("#cf-text").fill(TEXT_09)
    page.locator("#cf-text").press("Tab")
    expect(page.locator('[data-act="csave"]')).to_have_text("Сохранить как v4")
    page.locator('[data-act="csave"]').click()
    expect(item(page, "09")).to_contain_text("ждёт оценки")
    [draft] = api.puts
    new = next(c for c in draft["criteria"] if c["id"] == "09")
    assert (new["type"], new["w"], new["na"], new["text"]) == ("bool", 5, False, TEXT_09)


def test_run_evaluates_only_pending_criteria_with_progress(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    save_text_change(page)
    page.locator('[data-act="crun"]').click()
    view = page.locator('[data-view="checklist"]')
    expect(view).to_contain_text("Оценено 3 из 10 ответов по критериям")
    expect(view).to_contain_text("$0,02")
    expect(view).to_contain_text("40 с")
    expect(page.locator('[data-act="crun"]')).to_be_disabled()
    api.finish = True
    expect(item(page, "04")).not_to_contain_text("ждёт оценки")
    expect(page.locator('[data-act="crun"]')).to_have_count(0)
    assert api.runs == [{"dialogs": None, "criteria": ["04"]}]


def test_stop_cancels_pending_run(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    save_text_change(page)
    page.locator('[data-act="crun"]').click()
    page.locator('[data-view="checklist"] [data-act="stop"]').click()
    expect(page.locator('[data-view="checklist"] [data-act="stop"]')).to_have_count(0)
    assert api.cancels == 1


def test_weight_only_change_sends_no_run(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": []})
    item(page, "06").click()
    page.locator("#cf-w").fill("10")
    page.locator("#cf-w").press("Tab")
    page.locator('[data-act="csave"]').click()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 4 применяется")
    expect(item(page, "06")).to_contain_text("10")
    expect(page.locator('[data-view="checklist"]')).not_to_contain_text("ждёт оценки")
    expect(page.locator('[data-act="crun"]')).to_have_count(0)
    assert api.runs == []
    page.evaluate("location.hash = '#/queue'")
    expect(page.locator('[data-act="open"][data-id="call-024"]')).to_contain_text(
        "83,75"
    )  # было 82,94 при весе 15


@pytest.mark.parametrize(
    ("cid", "field", "typed"),
    [
        ("04", "#cf-name", "Полная консультация по запросу"),
        ("04", "#cf-text", "Оцените ответ, следующий шаг и срок."),
        ("04", "#cf-steps", "10: Полностью\n5: Частично\n0: Нет"),
        ("08", "#cf-q", "Оскорбление клиента\nПлатная услуга"),
    ],
)
def test_typing_key_by_key_keeps_every_character_and_focus(
    page: Page, web_url: str, cid: str, field: str, typed: str
) -> None:
    open_checklist(page, web_url)
    item(page, cid).click()
    page.locator(field).fill("")
    page.locator(field).press_sequentially(typed)
    expect(page.locator(field)).to_have_value(typed)
    expect(page.locator(field)).to_be_focused()


def test_typed_text_enables_save_before_the_field_loses_focus(page: Page, web_url: str) -> None:
    """На защите текст вводят и сразу жмут «Сохранить»: первый клик не должен пропасть."""
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    item(page, "04").click()
    page.locator("#cf-text").fill(TEXT_04)

    expect(page.locator('[data-act="csave"]')).to_be_enabled()
    page.locator('[data-act="csave"]').click()
    expect(item(page, "04")).to_contain_text("ждёт оценки")
    assert [next(c for c in d["criteria"] if c["id"] == "04")["text"] for d in api.puts] == [TEXT_04]
