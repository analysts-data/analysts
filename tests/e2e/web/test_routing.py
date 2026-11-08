"""Экран «Правила обработки»: правила словами, порядок, редактор с ошибкой 422 у поля,
«Проверить на диалоге».

Ответы /api/routing — по ветке llm-evaluation-routing (src/cqa/services/routing.py).
"""

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e

STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)
RULES = [
    {
        "id": "kazakh",
        "name": "Казахский",
        "enabled": True,
        "why": "На казахском модели ошибаются чаще.",
        "match": {"lang": ["KZ"]},
        "use": {"verifier": "jev"},
    },
    {
        "id": "calls",
        "name": "Звонки",
        "enabled": False,
        "why": None,
        "match": {"ch": "call"},
        "use": {"prosody": True},
    },
    {
        "id": "default",
        "name": "По умолчанию — общий режим",
        "enabled": True,
        "why": None,
        "match": {},
        "use": {},
    },
]
CONFIG = {
    "llm_mode": "live",
    "features": ["routing"],
    "providers": [{"id": "openrouter", "label": "OpenRouter"}, {"id": "local", "label": "Локальная модель"}],
}
EXPLAIN = {
    "dialog_id": "call-024",
    "rule": {"id": "calls", "name": "Звонки"},
    "rules": [
        {
            "id": "calls",
            "name": "Звонки",
            "enabled": True,
            "matched": True,
            "chosen": True,
            "conditions": [{"field": "ch", "ok": True, "text": "канал: звонок — нужно звонок"}],
        },
        {
            "id": "kazakh",
            "name": "Казахский",
            "enabled": True,
            "matched": False,
            "chosen": False,
            "conditions": [{"field": "lang", "ok": False, "text": "язык: RU — нужно одно из KZ"}],
        },
        {
            "id": "default",
            "name": "По умолчанию — общий режим",
            "enabled": True,
            "matched": True,
            "chosen": False,
            "conditions": [],
        },
    ],
}


def test_rules_read_as_sentences_reorder_edit_with_field_error_and_explain(page: Page, web_url: str) -> None:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "422" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    puts: list[list[dict[str, Any]]] = []

    def routing(route: Route) -> None:
        if route.request.method == "GET":
            return route.fulfill(json=RULES)
        body = route.request.post_data_json
        puts.append(body)
        if any(r["use"].get("llm_provider") == "local" for r in body):
            return route.fulfill(
                status=422,
                json={
                    "detail": "Правила не сохранены",
                    "fields": {"0.use.llm_provider": "нет ключа у провайдера «local»"},
                },
            )
        route.fulfill(json=body)

    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route("**/api/config", lambda r: r.fulfill(json=CONFIG))
    page.route("**/api/routing", routing)
    page.route("**/api/routing/explain", lambda r: r.fulfill(json=EXPLAIN))
    page.goto(f"{web_url}/#/routing")

    kz = page.locator('[data-rule="kazakh"]')
    expect(kz.locator('[data-act="rule-sentence"]')).to_have_text(
        "Если язык KZ → основная модель, второе мнение Jev"
    )
    expect(page.locator('[data-rule="calls"] [data-act="rule-sentence"]')).to_have_text(
        "Если звонок → основная модель, интонация"
    )

    kz.get_by_role("button", name="Ниже").click()
    expect(page.locator("[data-rule]").first).to_have_attribute("data-rule", "calls")
    assert [r["id"] for r in puts[-1]] == ["calls", "kazakh", "default"]

    page.locator('[data-rule="calls"]').get_by_role("button", name="Изменить").click()
    dlg = page.get_by_role("dialog", name="Изменить правило")
    dlg.get_by_label("Основная модель").select_option("local")
    dlg.get_by_label("Правило включено").check()
    dlg.get_by_role("button", name="Сохранить правило").click()
    expect(dlg.get_by_text("нет ключа у провайдера «local»")).to_be_visible()

    dlg.get_by_label("Основная модель").select_option("")
    dlg.get_by_role("button", name="Сохранить правило").click()
    expect(dlg).to_be_hidden()
    assert puts[-1][0] == {**RULES[1], "enabled": True}
    expect(page.locator('[data-rule="calls"]')).not_to_contain_text("Выключено")

    page.get_by_label("Диалог", exact=True).select_option("call-024")
    page.get_by_role("button", name="Проверить", exact=True).click()
    result = page.locator('[data-act="explain-result"]')
    expect(result).to_contain_text("Диалог возьмёт правило «Звонки»")
    expect(result.locator('[data-ok="yes"]')).to_have_text("канал: звонок — нужно звонок")
    expect(result.locator("[data-rule]")).to_have_count(1)  # правила ниже выбранного не важны
    assert errors == []
