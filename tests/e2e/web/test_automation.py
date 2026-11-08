import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e
STATE = (Path(__file__).resolve().parents[2] / "fixtures" / "state_prototype.json").read_text(
    encoding="utf-8"
)
SETTINGS = {
    "enabled": True,
    "sync": {"enabled": True, "every_min": 15, "sources": "all"},
    "evaluate": {
        "enabled": True,
        "on_new_dialogs": True,
        "sources": "all",
        "ch": "all",
        "lang": "all",
        "batch_size": 20,
        "priority": "normal",
        "max_per_hour": 60,
        "daily_budget_usd": 1.0,
        "quiet_hours": None,
        "only_unscored": True,
    },
    "after": {"classify_products": False, "evaluate_alerts": True, "prosody_for_calls": False},
}
CYCLE = {
    "trigger": "schedule",
    "started": "2026-11-08T07:00:00+05:00",
    "finished": "2026-11-08T07:01:00+05:00",
    "new_dialogs": 6,
    "evaluated": 6,
    "errors": [],
    "cost": 0.4,
    "skipped": None,
}


def status(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "next_run_at": "2026-11-08T07:15:00+05:00",
        "last_cycle": CYCLE,
        "today": {"dialogs_evaluated": 6, "cost_usd": 0.4, "budget_left": 0.6},
        "queue_length": 3,
    }


def test_automation_status_pause_settings_validation_and_switch(page: Page, web_url: str) -> None:
    problems: list[str] = []
    page.on(
        "console", lambda m: problems.append(m.text) if m.type == "error" and "422" not in m.text else None
    )
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.route("**/api/state", lambda r: r.fulfill(status=200, content_type="application/json", body=STATE))
    page.route(
        re.compile(r".*/api/sources$"),
        lambda r: r.fulfill(status=200, content_type="application/json", body="[]"),
    )
    saved: dict[str, Any] = json.loads(json.dumps(SETTINGS))
    puts: list[dict[str, Any]] = []
    state = {"now": "idle"}

    def api(route: Route) -> None:
        req, path = route.request, re.sub(r"^.*/api", "", route.request.url.split("?")[0])
        out: Any = None
        code = 200
        if path == "/automation" and req.method == "PUT":
            body: Any = req.post_data_json
            puts.append(body)
            if body["evaluate"]["batch_size"] > 500:
                code, out = (
                    422,
                    {
                        "detail": [
                            {
                                "loc": ["body", "evaluate", "batch_size"],
                                "msg": "Размер пачки — целое число от 1 до 500",
                            }
                        ]
                    },
                )
            else:
                saved.clear()
                saved.update(body)
                out = body
        elif path == "/automation":
            out = saved
        elif path == "/automation/status":
            out = status(state["now"])
        elif path == "/automation/pause":
            state["now"] = "paused"
            out = status("paused")
        elif path == "/automation/cycles":
            out = [CYCLE]
        route.fulfill(
            status=code if out is not None else 404, content_type="application/json", body=json.dumps(out)
        )

    page.route(re.compile(r".*/api/automation.*"), api)
    page.goto(f"{web_url}/#/automation")

    box = page.locator('[aria-label="Состояние"]')
    expect(box).to_contain_text("Ждёт следующего цикла")
    expect(box.locator("[data-today=evaluated]")).to_have_text("6")
    expect(box.locator("[data-today=budget]")).to_have_text("$0,40 из $1,00")
    expect(page.locator('[aria-label="Журнал циклов"] tbody tr')).to_have_text(
        re.compile("по расписанию.*успешно")
    )

    page.locator("[data-act=automation-pause]").click()
    expect(box).to_contain_text("На паузе")
    expect(page.locator("[data-act=automation-run]")).to_be_disabled()
    expect(box).to_contain_text("Продолжите, чтобы запустить цикл.")
    expect(page.locator("[data-act=automation-resume]")).to_be_visible()

    batch = page.get_by_label("Диалогов за цикл")
    batch.fill("900")
    page.locator("[data-act=automation-save]").click()
    expect(page.locator('[aria-label="Настройки"]')).to_contain_text("Размер пачки — целое число от 1 до 500")
    batch.fill("50")
    page.locator("[data-act=automation-save]").click()
    expect(page.locator("#toast")).to_contain_text("Настройки автоматизации сохранены.")
    assert puts[-1]["evaluate"]["batch_size"] == 50
    expect(page.locator("[data-act=automation-save]")).to_be_disabled()

    switch = page.get_by_role("switch", name="Автоматизация включена")
    expect(switch).to_have_attribute("aria-checked", "true")
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "false")
    assert puts[-1]["enabled"] is False
    assert problems == []
