"""Автоматизация через API: по умолчанию выключена и ничего не меняет; настройки с ошибками по полям."""

import time

from fastapi.testclient import TestClient


def test_default_off_status_and_lifespan_change_nothing(client: TestClient) -> None:
    with client:
        assert client.get("/api/automation").json()["enabled"] is False
        assert "automation" in client.get("/api/config").json()["features"]
        status = client.get("/api/automation/status").json()
        assert (status["state"], status["next_run_at"], status["last_cycle"]) == ("off", None, None)
        assert status["queue_length"] == 2
        assert client.post("/api/automation/run-now").status_code == 409
        time.sleep(0.05)
        assert client.get("/api/automation/cycles").json() == []
        assert all(not d["res"] for d in client.get("/api/state").json()["dialogs"])


def test_put_saves_merged_settings_and_bad_fields_are_422_in_russian(client: TestClient) -> None:
    saved = client.put("/api/automation", json={"enabled": True, "evaluate": {"batch_size": 3}}).json()
    assert (saved["enabled"], saved["evaluate"]["batch_size"], saved["sync"]["every_min"]) == (True, 3, 5)
    bad = client.put("/api/automation", json={"sync": {"every_min": 0}})
    assert bad.status_code == 422
    assert bad.json()["detail"] == [
        {"loc": ["body", "sync", "every_min"], "msg": "Период — целое число минут, не меньше 1"}
    ]
    assert client.get("/api/automation").json()["sync"]["every_min"] == 5


def test_enabled_scheduler_evaluates_the_queue_through_the_runner(client: TestClient) -> None:
    client.put("/api/automation", json={"enabled": True})
    with client:  # первый плановый цикл — сразу при старте
        deadline = time.monotonic() + 5
        while not client.get("/api/automation/cycles").json() and time.monotonic() < deadline:
            time.sleep(0.02)
        cycle = client.get("/api/automation/cycles").json()[0]
        assert (cycle["trigger"], cycle["queued"], cycle["evaluated"]) == ("schedule", 2, 2)
        assert client.get("/api/automation/status").json()["queue_length"] == 0
        actions = {e["action"] for e in client.get("/api/audit", params={"actor": "Автоматизация"}).json()}
        assert "automation.evaluate" in actions
        csv = client.get("/api/automation/cycles?format=csv")
        assert csv.headers["content-type"].startswith("text/csv") and "schedule" in csv.text
