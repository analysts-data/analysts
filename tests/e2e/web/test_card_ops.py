"""Карточка: оператор, продукт и маркеры в шапке, «Почему» из basis, история оценок и повторная оценка.

Ответы новых эндпоинтов подставляет `page.route` по черновику контракта (helpers-ops.md). Карточка не зовёт
их при открытии: только по клику.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Request, Route, expect

pytestmark = pytest.mark.e2e
STATE = Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json"
CARD = "call-024"
NEW_API = re.compile(
    r"/api/(dialogs/[^/]+/(history|markers|product|operator)|products|markers/|results/|runs)"
)

PRODUCT = {
    "status": "done",
    "id": "cards",
    "name": "Карты",
    "confidence": 0.82,
    "by": "jev",
    "basis": {
        "why": "Клиент спрашивает о лимите по карте",
        "ev": [3],
        "probs": {"cards": 0.82, "deposits": 0.11},
    },
}
MARKERS = [
    {
        "k": "repeat",
        "label": "Повторное обращение",
        "auto": True,
        "basis": {"rule": "Тот же клиент обращался за 7 дней", "threshold": 2, "value": 3, "ev": [3]},
    },
    {"k": "vip", "label": "VIP", "auto": False},
]
CATALOG = [
    {"k": "repeat", "label": "Повторное обращение"},
    {"k": "vip", "label": "VIP"},
    {"k": "complaint", "label": "Жалоба"},
]


def json_reply(route: Route, body: object, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class Card:
    """Состояние прототипа, которое /api/state отдаёт на каждый запрос: тест меняет его, как сервер."""

    def __init__(self, page: Page, web_url: str) -> None:
        self.page, self.web_url = page, web_url
        self.state = json.loads(STATE.read_text(encoding="utf-8"))
        self.errors: list[str] = []
        self.asked: list[str] = []  # новые эндпоинты, о которых карточка спросила
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", self._note)
        page.route("**/api/state", lambda r: json_reply(r, self.state))

    def _note(self, r: Request) -> None:
        if NEW_API.search(r.url):
            self.asked.append(f"{r.method} {r.url.split('/api', 1)[1]}")

    def dialog(self, dialog_id: str = CARD) -> dict[str, Any]:
        return next(d for d in self.state["dialogs"] if d["id"] == dialog_id)

    def open(self, dialog_id: str = CARD) -> None:
        self.page.goto(f"{self.web_url}/#/d/{dialog_id}")
        expect(self.page.locator('[data-view="d"] h1')).to_be_visible()


@pytest.fixture
def card(page: Page, web_url: str) -> Iterator[Card]:
    yield Card(page, web_url)


def with_ops(c: Card) -> dict[str, Any]:
    d = c.dialog()
    d.update(operator="Айгерим Сапарова", product=dict(PRODUCT), markers=[dict(m) for m in MARKERS])
    return d


def test_header_shows_operator_product_and_markers_without_new_requests(page: Page, card: Card) -> None:
    with_ops(card)
    card.open()
    ops = page.locator("[data-ops]").first
    expect(ops.locator('[data-ops="operator"]')).to_have_text("Айгерим Сапарова")
    expect(ops.locator('[data-ops="product"]')).to_have_text("Карты")
    expect(ops.locator("[data-marker]")).to_contain_text(["Повторное обращение", "VIP"])
    expect(ops.locator('[data-marker="repeat"] [data-act="why"]')).to_have_text("Почему")
    expect(ops.locator('[data-marker="vip"] [data-act="why"]')).to_have_count(0)  # ручной маркер без «Почему»
    assert card.asked == []
    assert card.errors == []


def test_state_without_ops_fields_shows_no_ops_block(page: Page, card: Card) -> None:
    card.open("p1-ru-003")
    expect(page.locator("[data-ops]")).to_have_count(0)
    assert card.asked == []
    assert card.errors == []


def test_why_shows_server_basis_for_product_marker_and_gross_error(page: Page, card: Card) -> None:
    with_ops(card)
    card.dialog()["res"]["08"]["basis"] = {"rule": "Платная услуга названа бесплатной", "value": "не найдено"}
    card.open()

    page.locator('[data-ops-item="product"] [data-act="why"]').click()
    why = page.get_by_role("dialog")
    expect(why).to_contain_text("Клиент спрашивает о лимите по карте")
    expect(why).to_contain_text("0,82")
    expect(why).to_contain_text("deposits")
    why.get_by_role("button", name="К реплике").click()
    expect(why).to_have_count(0)
    expect(page.locator('#tr [data-n="3"]')).to_be_in_viewport()

    page.locator('[data-marker="repeat"] [data-act="why"]').click()
    expect(why).to_contain_text("Тот же клиент обращался за 7 дней")
    expect(why).to_contain_text("Порог")
    expect(why).to_contain_text("Наблюдённое значение")
    page.keyboard.press("Escape")

    page.locator('.sum [data-act="why"]').click()
    expect(why).to_contain_text("Платная услуга названа бесплатной")
    assert card.asked == []
    assert card.errors == []


def test_intonation_badge_why_compares_line_with_speaker_norm(page: Page, card: Card) -> None:
    prosody = {
        "lines": [
            {"n": 3, "f0": 240, "range_st": 7.0, "db": 74.2, "wps": 2.1, "pause": 0.4, "flags": ["raised"]}
        ],
        "speakers": {"client": {"f0": 200.0, "db": 66.0, "wps": 2.5, "lines": 4}, "operator": None},
        "summary": ["Клиент повысил тон в реплике 3"],
    }
    page.route(f"**/api/dialogs/{CARD}/prosody", lambda r: json_reply(r, prosody))
    card.open()
    page.locator('#tr [data-n="3"] [data-act="why"]').click()
    why = page.get_by_role("dialog")
    expect(why).to_contain_text("240 Гц, обычно 200")
    expect(why).to_contain_text("74,2 дБ, обычно 66")
    assert card.errors == []


def test_operator_is_assigned_after_validation(page: Page, card: Card) -> None:
    card.dialog()["markers"] = []
    sent: list[Any] = []

    def put(route: Route) -> None:
        body = route.request.post_data_json
        sent.append(body)
        card.dialog()["operator"] = body["operator"]
        json_reply(route, body)

    page.route(f"**/api/dialogs/{CARD}/operator", put)
    card.open()
    item = page.locator('[data-ops-item="operator"]')
    expect(item).to_contain_text("не назначен")
    item.locator('[data-act="operator"]').click()
    expect(item.locator('[data-act="operator-save"]')).to_be_disabled()
    expect(item).to_contain_text("Введите имя оператора")
    item.get_by_label("Оператор").fill("Иван Петров")
    item.locator('[data-act="operator-save"]').click()
    expect(item.locator('[data-ops="operator"]')).to_have_text("Иван Петров")
    assert sent == [{"operator": "Иван Петров"}]
    assert card.errors == []


def test_marker_is_removed_returned_and_added_from_catalog(page: Page, card: Card) -> None:
    with_ops(card)
    sent: list[Any] = []

    def put(route: Route) -> None:
        body = route.request.post_data_json
        sent.append(body)
        d = card.dialog()
        d["markers"] = [m for m in d["markers"] if m["k"] not in body["remove"]] + [
            {**m, "auto": False} for m in CATALOG if m["k"] in body["add"]
        ]
        json_reply(route, d["markers"])

    page.route(f"**/api/dialogs/{CARD}/markers", put)
    page.route("**/api/markers/catalog", lambda r: json_reply(r, CATALOG))
    card.open()
    item = page.locator('[data-ops-item="markers"]')

    item.get_by_role("button", name="Снять маркер «VIP»").click()
    expect(item.locator('[data-marker="vip"]')).to_have_count(0)
    item.locator('[data-act="unmark-undo"]').click()
    expect(item.locator('[data-marker="vip"]')).to_be_visible()

    item.locator('[data-act="mark"]').click()
    pick = item.get_by_label("Маркер", exact=True)
    expect(pick.locator("option")).to_have_text(["Выберите…", "Жалоба"])  # уже стоящих в списке нет
    pick.select_option("complaint")
    item.locator('[data-act="mark-save"]').click()
    expect(item.locator('[data-marker="complaint"]')).to_have_text("Жалоба")
    assert sent == [
        {"add": [], "remove": ["vip"]},
        {"add": ["vip"], "remove": []},
        {"add": ["complaint"], "remove": []},
    ]
    assert card.errors == []


def test_product_is_corrected_from_catalog(page: Page, card: Card) -> None:
    with_ops(card)
    products = [{"id": "cards", "name": "Карты"}, {"id": "deposits", "name": "Вклады"}]
    sent: list[Any] = []

    def put(route: Route) -> None:
        sent.append(route.request.post_data_json)
        card.dialog()["product"] = {
            "status": "done",
            "id": "deposits",
            "name": "Вклады",
            "confidence": None,
            "by": "вручную",
        }
        json_reply(route, card.dialog()["product"])

    page.route("**/api/products", lambda r: json_reply(r, products))
    page.route(f"**/api/dialogs/{CARD}/product", put)
    card.open()
    item = page.locator('[data-ops-item="product"]')
    item.locator('[data-act="product"]').click()
    expect(item.locator('[data-act="product-save"]')).to_be_disabled()  # «Карты» уже указаны
    item.get_by_label("Продукт").select_option("deposits")
    item.locator('[data-act="product-save"]').click()
    expect(item.locator('[data-ops="product"]')).to_have_text("Вклады")
    expect(item).to_contain_text("вручную")
    assert sent == [{"id": "deposits"}]
    assert card.errors == []


def test_history_loads_on_click_and_older_answer_becomes_current(page: Page, card: Card) -> None:
    def row(rid: int, a: int, current: bool, stale: bool = False) -> dict[str, Any]:
        return {"id": rid, "created": f"2026-11-0{rid % 9}T10:00:00", "run_id": rid,
                "version": 2, "model": "qwen3-6",
                "a": a, "why": f"Оценка {rid}", "ev": [], "current": current, "stale": stale}  # fmt: skip

    history = {"06": [row(8, 7, True), row(5, 10, False), row(2, 4, False, stale=True)]}
    restored: list[str] = []

    def restore(route: Route) -> None:
        restored.append(route.request.url)
        card.dialog()["res"]["06"]["a"] = 10
        history["06"] = [row(9, 10, True), row(8, 7, False), row(5, 10, False), row(2, 4, False, stale=True)]
        json_reply(route, card.dialog()["res"]["06"])

    page.route(f"**/api/dialogs/{CARD}/history", lambda r: json_reply(r, history))
    page.route("**/api/results/5/restore", restore)
    card.open()
    page.click('.crit[data-cid="06"] [data-act="crit"]')
    assert card.asked == []  # история не грузится при открытии карточки и критерия

    page.locator('[data-act="history"][data-cid="06"]').click()
    table = page.locator('[data-history="06"]')
    expect(table.locator('[data-rid="8"]')).to_contain_text("текущая")
    expect(table.locator('[data-rid="2"]')).to_contain_text("прежний смысл")
    expect(table.locator('[data-rid="2"] [data-act="restore"]')).to_have_count(0)
    table.locator('[data-rid="5"] [data-act="restore"]').click()

    expect(page.locator('.crit[data-cid="06"] .crit-row')).to_contain_text("15 / 15")
    expect(table.locator('[data-rid="9"]')).to_contain_text("текущая")
    expect(page.locator("#toast")).to_contain_text("Итог пересчитан")
    assert len(restored) == 1
    assert card.errors == []


def test_rerun_sends_force_and_shows_evaluating_status(page: Page, card: Card) -> None:
    sent: list[Any] = []
    polls: list[int] = []

    def post(route: Route) -> None:
        sent.append(route.request.post_data_json)
        json_reply(route, {"run_id": 5})

    def progress(route: Route) -> None:
        polls.append(1)
        running = len(polls) < 3
        json_reply(route, {
            "done": 0 if running else 8, "total": 8, "cost": 0.0, "calls": 8, "eta_s": None, "errors": [],
            "status": "running" if running else "done", "skipped": 2,
            "dialogs": [{"id": CARD, "status": "running" if running else "done", "error": None,
                         "done": 0, "total": 8,
                         "skipped": 2}],
        })  # fmt: skip

    page.route(re.compile(r".*/api/runs$"), post)
    page.route("**/api/runs/5", progress)
    card.open()
    page.locator('[data-act="rerun"]').click()
    expect(page.locator('[data-eval="running"]')).to_have_text("Оценивается…")
    expect(page.locator('[data-act="rerun"]')).to_be_disabled()
    expect(page.locator("#toast")).to_contain_text("Не тронуты ручные ответы и решения: 2")
    expect(page.locator("[data-eval]")).to_have_count(0)
    expect(page.locator('[data-act="rerun"]')).to_be_enabled()
    assert sent == [{"dialogs": [CARD], "criteria": None, "force": True}]
    assert card.errors == []


def test_rerun_is_offered_only_to_qa(page: Page, card: Card) -> None:
    card.open()
    expect(page.locator('[data-act="rerun"]')).to_be_visible()
    page.locator('[data-act="role"][data-role="operator"]').click()
    expect(page.locator('[data-act="rerun"]')).to_have_count(0)
    assert card.errors == []
