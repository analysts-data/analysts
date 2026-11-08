"""Гибкость чек-листа (design/contract.md, «Настройка чек-листа»): «что если», нормировка, шкала оценок,
шаблоны, готовые чек-листы и песочница. Ответы сервера — заглушки page.route по контракту."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(encoding="utf-8")
)
BANDS = [
    {"min": 90, "label": "Отлично", "tone": "ok"},
    {"min": 75, "label": "Хорошо", "tone": None},
    {"min": 60, "label": "Требует внимания", "tone": "warn"},
    {"min": 0, "label": "Критично", "tone": "risk"},
]


def sim(dialogs: list[dict[str, Any]], **summary: Any) -> dict[str, Any]:
    return {
        "summary": {"dialogs": 10, "scored_before": 10, "scored_after": 10, "avg_before": 82.5,
                    "avg_after": 80.25, "delta": -2.25, "changed": 4, "up": 1, "down": 3, "lost_total": 0,
                    **summary},
        "groups": {"ch": [], "lang": []},
        "bands": [{**b, "before": 2, "after": 2} for b in BANDS],
        "moves": [{"from": "Отлично", "to": "Хорошо", "n": 1,
                   "text": "1 диалог перейдёт из „Отлично“ в „Хорошо“"}],
        "weights": [], "pending": [], "removed": [], "dialogs": dialogs, "findings": [], "save_errors": {},
        "insufficient": 0,
    }  # fmt: skip


def row(did: str, before: float, after: float, b0: str, b1: str, **extra: Any) -> dict[str, Any]:
    return {"id": did, "title": did, "ch": "chat", "lang": "ru", "before": before, "after": after,
            "delta": after - before, "band_before": b0, "band_after": b1, "why": ["вес «…» 20 → 25"],
            "text": "", "answers": [], **extra}  # fmt: skip


class Api:
    def __init__(self, page: Page) -> None:
        self.state = copy.deepcopy(STATE)
        self.posts: dict[str, list[Any]] = {}
        self.puts: list[dict[str, Any]] = []
        page.route("**/api/state", lambda r: r.fulfill(json=self.state))
        page.route("**/api/checklist", self.on_put)

    def on_put(self, route: Route) -> None:
        draft = route.request.post_data_json
        self.puts.append(draft)
        self.state["checklist"] = {**draft, "version": 4}
        self.state["versions"].append({"v": 4, "note": "веса"})
        route.fulfill(json={"version": 4, "pending": []})

    def stub(self, page: Page, path: str, reply: Any) -> None:
        """POST path: тело запроса — в posts[path], ответ — reply(тело) или reply как есть."""

        def on(route: Route) -> None:
            body = route.request.post_data_json
            self.posts.setdefault(path, []).append(body)
            route.fulfill(json=reply(body) if callable(reply) else reply)

        page.route(f"**/api{path}", on)


def open_checklist(page: Page, web_url: str) -> tuple[Api, Locator]:
    api = Api(page)
    page.goto(f"{web_url}/#/checklist")
    view = page.locator('[data-view="checklist"]')
    expect(view.locator("h1")).to_have_text("Чек-лист качества")
    return api, view


def item(view: Locator, cid: str) -> Locator:
    return view.locator(f'[data-act="csel"][data-cid="{cid}"]')


def set_weight(page: Page, view: Locator, cid: str, w: str) -> None:
    item(view, cid).click()
    page.locator("#cf-w").fill(w)
    page.locator("#cf-w").press("Tab")


def test_what_if_shows_new_totals_and_band_moves_and_save_needs_one_click(page: Page, web_url: str) -> None:
    api, view = open_checklist(page, web_url)
    api.stub(
        page,
        "/checklist/simulate",
        sim([row("call-024", 91, 88.5, "Отлично", "Хорошо"), row("p1-ru-003", 80, 79, "Хорошо", "Хорошо")]),
    )
    set_weight(page, view, "04", "25")
    view.locator('[data-act="csim"]').click()
    expect(view).to_contain_text("Средний итог 82,50 → 80,25 (-2,25)")
    expect(view).to_contain_text("Итог изменится у 4 из 10: выше у 1, ниже у 3.")
    expect(view).to_contain_text("Сменят оценку: 1")
    moved = view.locator('[data-sim] tr[data-did="call-024"]')
    expect(moved).to_contain_text("Отлично → Хорошо")
    expect(moved.get_by_role("link")).to_have_attribute("href", "#/d/call-024")
    expect(view.locator('[data-sim] tr[data-did="p1-ru-003"]')).to_have_count(0)  # оценка та же
    [draft] = api.posts["/checklist/simulate"]
    assert next(c for c in draft["criteria"] if c["id"] == "04")["w"] == 25

    set_weight(page, view, "04", "30")
    expect(view.get_by_text("Черновик изменён после расчёта")).to_be_visible()
    view.locator('[data-act="csave"]').click()  # без окна подтверждения
    expect(view.locator(".sub")).to_contain_text("Версия 4 применяется")
    assert len(api.puts) == 1


def test_normalize_is_undoable_and_bands_are_saved_with_field_errors(page: Page, web_url: str) -> None:
    api, view = open_checklist(page, web_url)
    norm = {"01": 10, "02": 14, "03": 19, "04": 24, "05": 14, "06": 14, "07": 5}
    api.stub(page, "/checklist/normalize", lambda d: {
        "checklist": {**d, "criteria": [{**c, "w": norm.get(c["id"], c["w"])} for c in d["criteria"]]},
        "changes": [{"id": c["id"], "name": c["name"], "from": c["w"], "to": norm[c["id"]], "exact": 0}
                    for c in d["criteria"] if c["id"] in norm],
        "shares": {}, "explanation": "Каждый вес × 100 / 105, остаток — наибольшим дробным частям.",
    })  # fmt: skip
    expect(view.locator('[data-act="cnorm"]')).to_have_count(0)  # сумма уже 100
    set_weight(page, view, "04", "25")
    expect(view.get_by_text("Сумма весов 105", exact=True)).to_be_visible()
    view.locator('[data-act="cnorm"]').click()
    expect(view.get_by_text("Сумма весов 100", exact=True)).to_be_visible()
    expect(view.locator("[data-norm]")).to_contain_text("04 25 → 24")
    expect(page.locator("#cf-w")).to_have_value("24")
    view.locator('[data-act="cunnorm"]').click()
    expect(view.get_by_text("Сумма весов 105", exact=True)).to_be_visible()
    expect(page.locator("#cf-w")).to_have_value("25")

    bodies: list[dict[str, Any]] = []

    def bands(route: Route) -> None:
        if route.request.method == "GET":
            return route.fulfill(
                json={
                    "bands": BANDS,
                    "why": "Договорённость руководства.",
                    "source": "default",
                    "saved_at": None,
                }
            )
        body = route.request.post_data_json
        bodies.append(body)
        if body["bands"][1]["min"] >= body["bands"][0]["min"]:
            msg = "Оценка 2: граница 95 должна быть меньше границы оценки 1 (90)"
            return route.fulfill(status=422, json={"detail": msg, "fields": {"bands.1.min": msg}})
        route.fulfill(json={**body, "source": "saved", "saved_at": "2026-11-08T10:00:00+00:00"})

    page.route("**/api/bands", bands)
    view.locator('[data-act="bands"]').click()
    border = view.get_by_label("Граница оценки 2")
    expect(border).to_have_value("75")
    border.fill("95")
    view.locator('[data-act="bsave"]').click()
    expect(view).to_contain_text("граница 95 должна быть меньше границы оценки 1")
    border.fill("80")
    view.get_by_label("Название оценки 3").fill("Нужно улучшить")
    view.locator('[data-act="bsave"]').click()
    expect(page.locator("#toast")).to_have_text("Шкала оценок сохранена.")
    expect(view).not_to_contain_text("должна быть меньше")
    assert bodies[-1] == {
        "bands": [{**BANDS[0]}, {**BANDS[1], "min": 80}, {**BANDS[2], "label": "Нужно улучшить"}, BANDS[3]],
        "why": "Договорённость руководства.",
    }


TEMPLATE = {
    "key": "product-offer",
    "tags": ["продажи"],
    "section": "Продажи и раскрытие условий",
    "why": "Пропущенная продажа.",
    "criterion": {"name": "Предложил подходящий продукт", "type": "bool", "w": 10, "na": True,
                  "naCond": "Запрос не касался продукта.", "text": "Да — оператор предложил продукт.",
                  "channel": "all"},
}  # fmt: skip


def test_preset_then_template_then_trial_on_twenty_dialogs(page: Page, web_url: str) -> None:
    api, view = open_checklist(page, web_url)
    preset = copy.deepcopy(STATE["checklist"])
    preset["version"], preset["criteria"][1]["name"] = 1, "Выявление цели клиента"
    page.route("**/api/checklist/presets", lambda r: r.fulfill(json=[
        {"key": "chat-support", "name": "Чат: поддержка", "description": "Для чатов.", "official": False,
         "criteria": 8, "checklist": preset},
    ]))  # fmt: skip
    view.locator("summary", has_text="Файл").click()
    view.locator('[data-act="cpreset"]').click()
    page.locator('dialog#dlg [data-act="preset"][data-key="chat-support"]').click()
    expect(page.locator("#toast")).to_contain_text("«Чат: поддержка» в черновике")
    expect(item(view, "02")).to_contain_text("Выявление цели клиента")
    expect(item(view, "02")).to_contain_text("изменён")
    expect(item(view, "01")).not_to_contain_text("изменён")

    page.route(
        "**/api/criteria/templates", lambda r: r.fulfill(json={"tags": ["продажи"], "templates": [TEMPLATE]})
    )
    view.locator('[data-act="cadd"]').click()
    view.locator('[data-act="ctpl"]').click()
    page.locator('dialog#dlg [data-act="tpl"][data-key="product-offer"]').click()
    expect(page.locator("#cf-name")).to_have_value("Предложил подходящий продукт")
    expect(view).to_contain_text("Продажи и раскрытие условий")
    expect(view.get_by_text("Сумма весов 110", exact=True)).to_be_visible()

    runs = {"n": 0, "done": False}

    def poll(route: Route) -> None:
        runs["n"] += 1
        done = runs["done"]
        route.fulfill(json={"done": 10 if done else 3, "total": 10, "cost": 0.01, "calls": 3, "eta_s": 5,
                            "errors": [], "status": "done" if done else "running"})  # fmt: skip

    page.route("**/api/runs/t1", poll)
    api.stub(
        page, "/checklist/trial", lambda b: {"run_id": "t1", "criteria": ["09"], "dialogs": b["dialogs"]}
    )
    answer = {"id": "09", "name": TEMPLATE["criterion"]["name"], "before": None, "after": "yes"}
    api.stub(
        page, "/checklist/simulate", sim([row("call-024", 91, 92, "Отлично", "Отлично", answers=[answer])])
    )
    trial = view.locator('[data-act="ctrial"]')
    expect(trial).to_have_text("Проверить черновик на 10 диалогах")  # в наборе 10, не больше 20
    trial.click()
    expect(view).to_contain_text("Песочница: оценено 3 из 10 ответов по критериям 09.")
    runs["done"] = True
    expect(view).to_contain_text("Песочница завершена: оценено 10 из 10")
    expect(view).to_contain_text("Ответы песочницы: 1")
    expect(view.locator("[data-sim]")).to_contain_text("Предложил подходящий продукт")
    [body] = api.posts["/checklist/trial"]
    assert body["dialogs"] == [d["id"] for d in STATE["dialogs"]]
    new = next(c for c in body["checklist"]["criteria"] if c["id"] == "09")
    assert (new["name"], new["w"], new["sec"]) == ("Предложил подходящий продукт", 10, 3)
    assert body["checklist"]["sections"][3] == "Продажи и раскрытие условий"
    [sim_body] = api.posts["/checklist/simulate"]
    assert sim_body == body["checklist"]  # сравнение — по тому же черновику
    assert api.puts == []
