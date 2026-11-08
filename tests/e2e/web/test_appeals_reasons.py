"""Коды причин решений на экране апелляций: выбор «Причина решения» по исходу, сводка «Изменено людьми»,
каталог кодов для специалиста КК (design/contract.md, «Коды причин решений»)."""

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
REASONS = [
    {"code": "misread", "label": "Модель неверно поняла реплику", "applies": "changed"},
    {"code": "by_rules", "label": "Оценка верна по регламенту", "applies": "confirmed"},
    {"code": "other", "label": "Другое", "applies": "both"},
]
STATS = {
    "decisions": 2,
    "reasons": [
        {"code": "misread", "label": "Модель неверно поняла реплику", "cid": "04", "name": "Срок",
         "status": "changed", "n": 1, "share": 0.5},
    ],
    "modified": {
        "pairs": 5, "changed": 2, "share": 0.4,
        "criteria": [{"id": "04", "name": "Срок вывода", "pairs": 2, "changed": 1, "share": 0.5}],
        "langs": [{"key": "RU", "pairs": 4, "changed": 1, "share": 0.25}],
    },
}  # fmt: skip


class Api:
    """GET /api/state, каталог причин, сводка и решение — как сервер; записи складываются в writes."""

    def __init__(self, page: Page) -> None:
        self.state: dict[str, Any] = copy.deepcopy(STATE)
        self.reasons = copy.deepcopy(REASONS)
        self.writes: list[tuple[str, Any]] = []
        self.errors: list[str] = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.route("**/api/state", lambda r: r.fulfill(json=self.state))
        page.route("**/api/appeals/stats", lambda r: r.fulfill(json=STATS))
        page.route("**/api/appeals/reasons", self.catalog)
        page.route("**/api/appeals/*/decision", self.decide)

    def catalog(self, route: Route) -> None:
        if route.request.method == "PUT":
            self.reasons = route.request.post_data_json
            self.writes.append(("reasons", self.reasons))
        route.fulfill(json=self.reasons)

    def decide(self, route: Route) -> None:
        body = route.request.post_data_json
        self.writes.append(("decision", body))
        a = next(x for x in self.state["appeals"] if x["id"] == route.request.url.split("/")[-2])
        a.update(body, status="confirmed" if body["to"] == a["from"] else "changed", decidedAt="07.11 16:00")
        route.fulfill(json=a)


def options(page: Page) -> list[str]:
    return page.locator('[data-act="dcode"] option').all_inner_texts()


def test_reason_code_follows_the_outcome_and_is_sent_with_the_decision(page: Page, web_url: str) -> None:
    api = Api(page)
    page.goto(f"{web_url}/#/appeals/a1")
    page.locator('[data-act="role"][data-role="reviewer"]').click()
    summary = page.get_by_label("Изменено людьми")
    expect(summary).to_contain_text("40%")
    expect(summary).to_contain_text("2 из 5 ответов модели")
    expect(summary).to_contain_text("Срок вывода")
    expect(summary).to_contain_text("Модель неверно поняла реплику")
    assert options(page) == ["Без кода", "Модель неверно поняла реплику", "Другое"]
    page.get_by_label("Подтвердить оценку").check()
    assert options(page) == ["Без кода", "Оценка верна по регламенту", "Другое"]
    page.get_by_label("Изменить оценку").check()
    page.locator('[data-act="dcode"]').select_option("misread")
    expect(page.locator('[data-view="appeals"] textarea')).to_have_count(1)
    page.get_by_label("Причина решения, обязательно").fill("Срок назван во второй реплике")
    page.locator('[data-act="decide"]').click()
    expect(page.get_by_label("История решений")).to_contain_text("Модель неверно поняла реплику")
    assert api.writes == [
        ("decision", {"to": 20, "reason": "Срок назван во второй реплике", "reviewer": "Проверяющий",
                      "reason_code": "misread"}),
    ]  # fmt: skip
    assert api.errors == []


def test_qa_edits_the_reason_catalog(page: Page, web_url: str) -> None:
    api = Api(page)
    page.goto(f"{web_url}/#/appeals")
    page.locator('[data-act="reasons"]').click()
    dialog = page.get_by_role("dialog", name="Коды причин")
    dialog.get_by_role("button", name="Добавить код").click()
    row = dialog.locator("li").last
    row.get_by_label("Код", exact=True).fill("asr")
    row.get_by_label("Название", exact=True).fill("Ошибка распознавания речи")
    row.get_by_label("Подходит к решению").select_option("changed")
    dialog.locator("li").first.get_by_role("button", name="Удалить код").click()
    dialog.locator('[data-act="reasons-save"]').click()
    expect(dialog).to_have_count(0)
    expect(page.locator("#toast")).to_contain_text("Коды причин сохранены: 3.")
    assert api.writes == [
        (
            "reasons",
            [*REASONS[1:], {"code": "asr", "label": "Ошибка распознавания речи", "applies": "changed"}],
        )
    ]
    assert api.errors == []
