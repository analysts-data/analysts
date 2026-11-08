"""Темы обращений через API: справочник, ручная тема, темы в запуске, аналитика и отчёт, охрана звонков."""

import json
import sqlite3
import time
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.compose import build_classifier
from cqa.domain.models import Dialog, Product, ProductTag, RiskKind, RiskMark
from cqa.http.app import create_app
from cqa.services.runs import Classifier
from cqa.settings import Settings
from fakes import FIXTURES, FakeEvaluator, FakeSource

SEED = json.loads((FIXTURES / "products.json").read_text(encoding="utf-8"))


class OneTopic:
    risks: Sequence[RiskKind] = ()

    async def classify(
        self, dialog: Dialog, products: Sequence[Product]
    ) -> tuple[ProductTag, list[RiskMark]]:
        mark = RiskMark(k="churn", label="Угроза ухода", lines=[1], basis="Грозит уйти (реплика 1)")
        return ProductTag(
            status="done", id="funding", name="Пополнение и вывод средств", by="m", cost=0.0001
        ), [mark]


def _client(settings: Settings, conn: sqlite3.Connection, classifier: Classifier | None) -> TestClient:
    return TestClient(
        create_app(settings, source=FakeSource(), evaluator=FakeEvaluator(), conn=conn, classifier=classifier)
    )


@pytest.fixture
def api(settings: Settings, store: Store, conn: sqlite3.Connection) -> Iterator[TestClient]:
    with _client(settings, conn, OneTopic()) as client:
        yield client


def _wait(client: TestClient, run_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + 2
    while (run := client.get(f"/api/runs/{run_id}").json())["status"] == "running":
        assert time.monotonic() < deadline, "no progress within 2 seconds"
        time.sleep(0.01)
    return run


def _products(client: TestClient) -> dict[str, Any]:
    return {d["id"]: d.get("product") for d in client.get("/api/state").json()["dialogs"]}


def test_taxonomy_is_seeded_and_replaced_whole(api: TestClient) -> None:
    assert api.get("/api/products").json() == SEED
    new = [{"id": "cards", "name": "Карты", "description": "Выпуск и блокировка карт"}]
    assert api.put("/api/products", json=new).json() == new
    assert api.get("/api/products").json() == new
    assert api.put("/api/products", json=new + new).status_code == 422
    assert api.put("/api/products", json=[{"id": "Не код", "name": "x"}]).status_code == 422


def test_run_classifies_dialogs_and_state_carries_the_topic(api: TestClient) -> None:
    run = _wait(api, api.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"])
    assert run["products"] == {"done": 2, "total": 2, "errors": 0, "cost": pytest.approx(0.0002)}
    topics = _products(api)
    assert {d: (p["status"], p["id"], p["by"]) for d, p in topics.items()} == {
        "call-024": ("done", "funding", "m"),
        "p1-ru-003": ("done", "funding", "m"),
    }
    risks = {d["id"]: d["risks"] for d in api.get("/api/state").json()["dialogs"]}
    assert risks["call-024"] == [
        {"k": "churn", "label": "Угроза ухода", "lines": [1], "basis": "Грозит уйти (реплика 1)"}
    ]


def test_manual_topic_overrides_the_model_and_is_kept(api: TestClient) -> None:
    r = api.put("/api/dialogs/call-024/product", json={"id": "kyc", "reason": "Просит обновить документы"})
    assert r.status_code == 200, r.text
    assert (r.json()["id"], r.json()["by"], r.json()["basis"]["why"]) == (
        "kyc",
        "вручную",
        "Просит обновить документы",
    )
    _wait(api, api.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"])
    assert _products(api)["call-024"]["id"] == "kyc"
    assert api.put("/api/dialogs/nope/product", json={"id": "kyc"}).status_code == 404
    assert api.put("/api/dialogs/call-024/product", json={"id": "loans"}).status_code == 422


def test_stats_and_report_by_topic(api: TestClient) -> None:
    _wait(api, api.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"])
    stats = {s["id"]: s for s in api.get("/api/products/stats").json()}
    assert list(stats) == [p["id"] for p in SEED]
    funding = stats["funding"]
    assert (funding["dialogs"], funding["scored"]) == (2, 2)
    assert set(funding) == {
        "id", "name", "dialogs", "scored", "avg_total", "risk_share", "no_next_step_share",
        "needs_review", "reasons", "weakest", "risks",
    }  # fmt: skip
    rep = api.get("/api/report?format=json").json()
    assert [p["id"] for p in rep["products"]] == ["funding"]
    assert "По продуктам" in api.get("/api/report?format=md").text


def test_real_call_is_not_sent_for_a_topic_without_permission(store: Store, conn: sqlite3.Connection) -> None:
    settings = Settings(
        _env_file=None, db_path=":memory:", llm_mode="live", llm_api_key="k", llm_base_url="https://llm.test"
    )
    reply = (
        '{"reason_ru": "Клиент ждёт вывод (реплика 2)", "turn_ids": [2], "answer": "funding", "risks": []}'
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://llm.test/chat/completions").respond(
            200, json={"choices": [{"message": {"content": reply}}], "usage": {}}
        )
        with _client(settings, conn, build_classifier(settings)) as client:
            _wait(client, client.post("/api/runs", json={"dialogs": None, "criteria": None}).json()["run_id"])
            topics = _products(client)
    call = topics["call-024"]
    assert call["status"] == "error" and "CQA_ALLOW_REAL_DATA" in call["error"]
    assert topics["p1-ru-003"]["status"] == "done"
    assert route.call_count == 1  # только чат
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"] == {"type": "json_object"}  # без рассуждения: короткий дешёвый ответ
