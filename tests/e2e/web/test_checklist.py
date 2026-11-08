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
        self.errors: list[str] = []
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
        if self.errors:  # as replay without a recording: done, answers still missing
            return route.fulfill(
                json={**RUNNING, "done": 10, "eta_s": 0, "errors": self.errors, "status": "done"}
            )
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
    expect(page.locator("#toast")).to_have_text("Оценка запущена.")
    expect(view).to_contain_text("Оценено 3 из 10 ответов по критериям")
    expect(view).to_contain_text("$0,02")
    expect(view).to_contain_text("40 с")
    expect(page.locator('[data-act="crun"]')).to_be_disabled()
    api.finish = True
    expect(item(page, "04")).not_to_contain_text("ждёт оценки")
    expect(page.locator('[data-act="crun"]')).to_have_count(0)
    expect(page.locator("#toast")).to_have_text("Оценка завершена: оценено 10 из 10 ответов по критериям.")
    assert api.runs == [{"dialogs": None, "criteria": ["04"]}]


def test_run_with_errors_is_reported_on_the_checklist(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    save_text_change(page)
    api.finish = True
    api.errors = ["p1-ru-003: Нет записи ответа модели"]
    page.locator('[data-act="crun"]').click()
    view = page.locator('[data-view="checklist"]')
    note = "Оценка завершена с ошибками: 1, в диалогах: 1"
    expect(page.locator("#toast")).to_contain_text(note)
    expect(view).to_contain_text(note)
    view.get_by_text("Показать ошибки").click()
    expect(view.get_by_role("link", name="p1-ru-003")).to_have_attribute("href", "#/d/p1-ru-003")
    expect(view).to_contain_text("Нет записи ответа модели")
    expect(page.locator('[data-act="crun"]')).to_be_enabled()  # 04 всё ещё ждёт оценки
    api.put_reply = {"version": 5, "pending": []}  # новая версия: ошибки прошлого запуска уже не про неё
    item(page, "06").click()
    page.locator("#cf-w").fill("10")
    page.locator("#cf-w").press("Tab")
    page.locator('[data-act="csave"]').click()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 5 применяется")
    expect(view).not_to_contain_text("с ошибками")


def test_deleted_pending_criterion_leaves_the_banner(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["09"]})
    page.locator('[data-act="cadd"]').click()
    page.locator('[data-act="csave"]').click()
    expect(item(page, "09")).to_contain_text("ждёт оценки")
    expect(page.locator('[data-act="crun"]')).to_be_visible()
    api.put_reply = {"version": 5, "pending": []}
    item(page, "09").click()
    page.locator('[data-act="cdel"]').click()
    page.locator('[data-act="csave"]').click()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 5 применяется")
    expect(page.locator('[data-act="crun"]')).to_have_count(0)
    expect(page.locator('[data-view="checklist"]')).not_to_contain_text("ждёт оценки")


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


RULES = "N/A ставь только там, где он разрешён. Время ответа не оценивай."
CALL_04 = "На звонке срок можно назвать устно, ссылку присылать не нужно."


def test_rules_change_marks_every_criterion_and_is_saved_with_the_draft(page: Page, web_url: str) -> None:
    ids = [c["id"] for c in json.loads(STATE)["checklist"]["criteria"]]
    api = open_checklist(page, web_url, {"version": 4, "pending": ids})
    rules = page.locator("#cl-rules")
    expect(rules).to_have_value(api.state["checklist"]["rules"])
    expect(page.get_by_text("Смена правил меняет смысл всех критериев")).to_be_visible()
    rules.fill(RULES)
    expect(page.locator('[data-act="csave"]')).to_be_enabled()
    item(page, "03").click()
    expect(item(page, "03")).to_contain_text("изменён")
    expect(item(page, "08")).to_contain_text("изменён")
    page.locator('[data-act="csave"]').click()
    for cid in ids:
        expect(item(page, cid)).to_contain_text("ждёт оценки")
    [draft] = api.puts
    assert draft["rules"] == RULES


def test_call_addendum_is_offered_for_every_type_and_empty_means_none(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    for cid in ("01", "08", "04"):  # bool, flag, scale
        item(page, cid).click()
        expect(page.locator("#cf-call")).to_have_value("")
    expect(
        page.get_by_text("Модель получает его только на звонках, запрос по чатам не меняется")
    ).to_be_visible()
    page.locator("#cf-call").fill(CALL_04)
    expect(page.locator('[data-act="csave"]')).to_be_enabled()
    page.locator("#cf-call").fill("  ")
    expect(page.locator('[data-act="csave"]')).to_be_disabled()
    page.locator("#cf-call").fill(CALL_04)
    page.locator('[data-act="csave"]').click()
    expect(item(page, "04")).to_contain_text("ждёт оценки")
    expect(page.locator("#cf-call")).to_have_value(CALL_04)

    api.put_reply = {"version": 5, "pending": ["04"]}
    page.locator("#cf-call").fill("")
    page.locator('[data-act="csave"]').click()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 5 применяется")
    sent = [next(c for c in d["criteria"] if c["id"] == "04").get("call") for d in api.puts]
    assert sent == [CALL_04, None]
    assert all("call" not in c for c in api.puts[0]["criteria"] if c["id"] != "04")


@pytest.mark.parametrize(
    ("cid", "field", "typed"),
    [
        ("04", "#cf-name", "Полная консультация по запросу"),
        ("04", "#cf-text", "Оцените ответ, следующий шаг и срок."),
        ("04", "#cf-steps", "10: Полностью\n5: Частично\n0: Нет"),
        ("08", "#cf-q", "Оскорбление клиента\nПлатная услуга"),
        ("04", "#cf-call", "Срок можно назвать устно."),
        ("04", "#cl-rules", "N/A только где разрешён.\nВремя ответа не оцениваем."),
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


XSS = "<img src=x onerror=alert(1)>"
NOT_CHECKLIST = "Файл не похож на чек-лист"


def import_file(page: Page, body: bytes) -> None:
    page.set_input_files(
        '[data-act="cimport"]', files=[{"name": "cl.json", "mimeType": "application/json", "buffer": body}]
    )


def export_menu(page: Page) -> Locator:
    page.locator('[data-view="checklist"] summary', has_text="Экспорт").click()
    return page.locator('[data-view="checklist"] .menu-pop')


def test_export_downloads_applied_version(page: Page, web_url: str) -> None:
    """Файл строит сервер (tests/integration/test_api_checklist_export.py), здесь — что качается и откуда.
    Скачивание по <a download> мимо page.route, поэтому тело ответа здесь не подменить."""
    open_checklist(page, web_url)
    item(page, "01").click()
    page.locator("#cf-w").fill("20")
    page.locator("#cf-w").press("Tab")
    export_menu(page)
    with page.expect_download() as d:
        page.locator('[data-act="cexport"]').click()
    assert d.value.url == f"{web_url}/api/checklist/export?v=3&format=json"  # применяемая версия, не черновик
    expect(page.locator('[data-act="cexport"]')).to_have_text("JSON")
    page.locator('[data-act="role"][data-role="operator"]').click()
    expect(page.locator('[data-view="checklist"] summary', has_text="Экспорт")).to_be_visible()


def test_export_menu_offers_every_format_for_the_selected_version(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    menu = export_menu(page)
    links = {name: menu.get_by_role("link", name=name) for name in ("Excel (CSV)", "Markdown")}
    for name, fmt in (("Excel (CSV)", "csv"), ("Markdown", "md")):
        expect(links[name]).to_have_attribute("href", f"/api/checklist/export?v=3&format={fmt}")
        expect(links[name]).to_have_attribute("download", "")
    memo = menu.get_by_role("link", name="Памятка для печати")
    expect(memo).to_have_attribute("target", "_blank")
    menu.locator("select").select_option("1")
    expect(menu).to_be_visible()  # смена версии не закрывает меню
    expect(links["Excel (CSV)"]).to_have_attribute("href", "/api/checklist/export?v=1&format=csv")
    expect(page.locator('[data-act="cexport"]')).to_have_attribute(
        "href", "/api/checklist/export?v=1&format=json"
    )
    with page.context.expect_page() as popup:
        memo.click()
    assert popup.value.url == f"{web_url}/api/checklist/export?v=1&format=html"
    expect(menu).to_be_hidden()  # пункт меню закрывает его


DIFF_MD = f"# Что изменится: v2 → v3\n\n## Изменены\n\n### 04 «{XSS}»\n\n- вес: 15 → 20\n"


def test_compare_with_current_shows_server_diff_in_a_dialog(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    urls: list[str] = []
    page.route(
        "**/api/checklist/diff*",
        lambda route: (
            urls.append(route.request.url),
            route.fulfill(body=DIFF_MD, content_type="text/markdown"),
        ),
    )
    view = page.locator('[data-view="checklist"]')
    expect(view.locator('[data-act="cdiff"][data-v="3"]')).to_have_count(0)  # текущую не с чем сравнивать
    view.locator('[data-act="cdiff"][data-v="2"]').click()
    dialog = page.locator("dialog#dlg")
    expect(dialog).to_be_visible()
    expect(dialog.locator("pre")).to_have_text(DIFF_MD.rstrip("\n"))
    expect(dialog.locator("img")).to_have_count(0)
    assert urls == [f"{web_url}/api/checklist/diff?from=2&to=3&format=md"]
    dialog.get_by_role("button", name="Закрыть").click()
    expect(dialog).to_be_hidden()


def test_what_changes_posts_the_draft_and_shows_the_diff(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    posts: list[dict[str, Any]] = []

    def reply(route: Route) -> None:
        assert route.request.method == "POST"
        posts.append(route.request.post_data_json)
        route.fulfill(body="# Что изменится: v3 → v4\n\n- вес: 10 → 20\n", content_type="text/markdown")

    page.route("**/api/checklist/diff*", reply)
    what = page.locator('[data-act="cwhat"]')
    expect(what).to_be_disabled()  # черновик совпадает с версией
    item(page, "01").click()
    page.locator("#cf-name").fill("Приветствие")  # без перерисовки: кнопку включает syncSave
    expect(what).to_be_enabled()
    what.click()
    expect(page.locator("dialog#dlg pre")).to_contain_text("- вес: 10 → 20")
    [draft] = posts
    assert draft["version"] == 3 and draft["criteria"][0]["name"] == "Приветствие"


def test_import_fills_draft_and_save_sends_it(page: Page, web_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    api = open_checklist(page, web_url, {"version": 4, "pending": []})
    cl = json.loads(STATE)["checklist"]
    cl["version"], cl["rules"] = 1, "Новые общие правила."
    cl["criteria"][0]["w"], cl["criteria"][1]["name"] = 15, XSS
    cl["criteria"][2]["call"] = "На звонке достаточно устного согласия."
    import_file(page, json.dumps(cl, ensure_ascii=False).encode())
    expect(page.locator("#toast")).to_have_text(
        "Чек-лист из файла в черновике. Проверьте изменения и сохраните как v4."
    )
    expect(page.get_by_text("Есть несохранённые изменения")).to_be_visible()
    expect(item(page, "01")).to_contain_text("изменён")
    expect(item(page, "02")).to_contain_text(XSS)
    expect(item(page, "02").locator("img")).to_have_count(0)
    page.locator('[data-act="csave"]').click()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 4 применяется")
    [draft] = api.puts
    assert draft["version"] == 3
    assert draft["criteria"][0]["w"] == 15
    assert draft["rules"] == "Новые общие правила."
    assert draft["criteria"][2]["call"] == "На звонке достаточно устного согласия."
    assert errors == []


@pytest.mark.parametrize("body", [b'{"foo": 1}', "не json".encode()])
def test_import_rejects_non_checklist(page: Page, web_url: str, body: bytes) -> None:
    open_checklist(page, web_url)
    import_file(page, body)
    expect(page.locator("#toast")).to_contain_text(NOT_CHECKLIST)
    expect(page.get_by_text("Есть несохранённые изменения")).to_have_count(0)


def test_import_disabled_while_draft_dirty(page: Page, web_url: str) -> None:
    open_checklist(page, web_url)
    cimport = page.locator('[data-act="cimport"]')
    expect(cimport).to_be_enabled()
    item(page, "01").click()
    page.locator("#cf-w").fill("20")
    page.locator("#cf-w").press("Tab")
    expect(cimport).to_be_disabled()
    page.locator('[data-act="creset"]').click()
    expect(cimport).to_be_enabled()
    page.locator("#cf-name").fill("Приветствие")  # без ухода из поля: только syncSave, без перерисовки
    expect(cimport).to_be_disabled()
    expect(page.locator("#cf-name")).to_have_value("Приветствие")


def test_jev_import_merges_questions_into_draft_by_id(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["01", "09"]})
    greet = {
        "type": "noul",
        "instructions": "Оператор поздоровался.",
        "criteria": {"true": "Да", "false": "Нет"},
    }
    term = {
        "type": "choice",
        "instructions": "Оператор назвал срок.",
        "criteria": {"yes": "Да", "no": "Нет", "na": "Срок не нужен"},
    }
    body = json.dumps({"questions": {"01": greet, "09": term}}, ensure_ascii=False).encode()
    expect(page.locator('[data-view="checklist"] label:has([data-act="cjevimport"])')).to_have_text(
        "Импорт из формата Jev"
    )
    expect(page.locator('[data-act="cjevexport"]')).to_have_text("Экспорт в формат Jev")
    page.set_input_files(
        '[data-act="cjevimport"]', files=[{"name": "q.json", "mimeType": "application/json", "buffer": body}]
    )
    expect(page.locator("#toast")).to_have_text(
        "Добавлено 1, обновлено 1. Проверьте веса и сохраните версию."
    )
    expect(item(page, "01")).to_contain_text("изменён")
    expect(item(page, "09")).to_contain_text("N/A")
    page.locator('[data-act="csave"]').click()
    expect(page.locator('[data-view="checklist"] .sub')).to_contain_text("Версия 4 применяется")
    [draft] = api.puts
    old = next(c for c in CHECKLIST["criteria"] if c["id"] == "01")
    c01, c09 = (next(c for c in draft["criteria"] if c["id"] == cid) for cid in ("01", "09"))
    assert (c01["text"], c01["jev"], c01["w"], c01["name"]) == (
        greet["instructions"],
        greet,
        old["w"],
        old["name"],
    )
    assert (c09["type"], c09["na"], c09["naCond"], c09["jev"]) == ("bool", True, "Срок не нужен", term)


def test_run_progress_survives_page_reload(page: Page, web_url: str) -> None:
    api = open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    save_text_change(page)
    page.locator('[data-act="crun"]').click()
    expect(page.locator('[data-view="checklist"]')).to_contain_text("Оценено 3 из 10 ответов по критериям")
    assert page.evaluate("localStorage.getItem('cqa.run')") == "r9"

    page.reload()
    expect(page.locator('[data-view="checklist"]')).to_contain_text("Оценено 3 из 10 ответов по критериям")
    expect(page.locator('[data-act="stop"]')).to_be_visible()

    api.finish = True
    expect(page.locator('[data-act="stop"]')).to_have_count(0)
    page.wait_for_function("localStorage.getItem('cqa.run') === null")
    assert page.evaluate("localStorage.getItem('cqa.run')") is None


@pytest.mark.parametrize(
    ("cancelled", "missing"),
    [(True, False), (False, True)],
    ids=["cancelled", "unknown-404"],
)
def test_finished_or_unknown_stored_run_is_forgotten(
    page: Page, web_url: str, cancelled: bool, missing: bool
) -> None:
    page.add_init_script("localStorage.setItem('cqa.run', 'r9')")
    api = Api(page)
    if cancelled:
        api.cancels = 1  # как сервер после остановки: статус уже не running
    if missing:
        page.route(
            "**/api/runs/r9",
            lambda route: route.fulfill(status=404, json={"detail": "Запуск не найден"}),
        )
    page.goto(f"{web_url}/#/checklist")
    expect(page.locator('[data-view="checklist"] h1')).to_have_text("Чек-лист качества")
    expect(page.locator('[data-act="stop"]')).to_have_count(0)
    expect(page.locator("#toast")).to_be_hidden()
    page.wait_for_function("localStorage.getItem('cqa.run') === null")


def test_run_works_without_local_storage(page: Page, web_url: str) -> None:
    page.add_init_script(
        "Object.defineProperty(window, 'localStorage', "
        "{get() { throw new DOMException('denied', 'SecurityError'); }})"
    )
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    open_checklist(page, web_url, {"version": 4, "pending": ["04"]})
    save_text_change(page)
    page.locator('[data-act="crun"]').click()
    expect(page.locator('[data-view="checklist"]')).to_contain_text("Оценено 3 из 10 ответов по критериям")
    assert errors == []
