"""Источники диалогов через HTTP: реестр, проверка с предпросмотром, синхронизация, webhook, учёт, SSRF.

Внешние сервисы — respx; DNS — подменный резолвер, сеть не нужна. Данные синтетические.
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cqa.adapters.http_source import HttpSource
from cqa.adapters.store import connect
from cqa.http.app import create_app
from cqa.settings import Settings
from fakes import FakeEvaluator, FakeSource

API = "https://chat.test/v1/conversations"
SECRET = "Bearer s3cr3t-value"
MAPPING = {
    "conversation_id": "id",
    "channel": "type",
    "transcript": "messages",
    "speaker": "from",
    "text": "body",
    "timestamp": "time",
    "operator": "agent.name",
}


def _chat(n: int) -> dict[str, Any]:
    return {
        "id": f"c{n}",
        "type": "chat",
        "agent": {"name": f"Оператор {n}"},
        "messages": [
            {"from": "customer", "body": f"Вопрос номер {n}", "time": "00:01"},
            {"from": "agent", "body": "Здравствуйте! Помогу", "time": "00:20"},
        ],
    }


PAYLOAD = {"data": {"items": [_chat(n) for n in range(1, 6)] + [{"id": "bad", "messages": None}]}}
HTTP_SOURCE = {
    "name": "Чат-платформа",
    "kind": "http_json",
    "service": "ChatDesk",
    "product_default": "Карты",
    "config": {"url": API, "auth_header": "Authorization", "records_path": "data.items", "mapping": MAPPING},
    "secret": SECRET,
    "schedule_min": 15,
}
WEBHOOK = {"name": "Телефония", "kind": "webhook", "channel_default": "call", "config": {"mapping": MAPPING}}


async def _resolve(host: str) -> list[str]:
    return {"chat.test": ["93.184.216.34"], "intranet.test": ["10.0.0.5"]}.get(host, [host])


def _app(settings: Settings, *, allow_private: bool = False) -> TestClient:
    app = create_app(settings, source=FakeSource(), evaluator=FakeEvaluator(), conn=connect(":memory:"))
    app.state.syncer.http = HttpSource(httpx.AsyncClient(), allow_private=allow_private, resolve=_resolve)
    return TestClient(app)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return _app(settings)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


def test_create_lists_the_source_without_its_secret(client: TestClient) -> None:
    created = client.post("/api/sources", json=HTTP_SOURCE)
    assert created.status_code == 200
    body = created.json()
    assert (body["id"], body["has_secret"], body["kind"]) == ("src1", True, "http_json")
    listed = client.get("/api/sources")
    assert [s["id"] for s in listed.json()] == ["org", "file", "paste", "api", "src1"]
    assert "s3cr3t" not in created.text + listed.text
    assert "sources" in client.get("/api/config").json()["features"]


def test_bad_config_is_a_field_level_422(client: TestClient) -> None:
    bad = {**HTTP_SOURCE, "config": {"url": "ftp://chat.test", "mapping": {"conversation_id": "id"}}}
    response = client.post("/api/sources", json=bad)
    assert response.status_code == 422
    assert set(response.json()["fields"]) == {
        "config.url",
        "config.mapping.transcript",
        "config.mapping.speaker",
        "config.mapping.text",
    }


def test_draft_test_previews_three_records_and_stores_nothing(
    client: TestClient, api: respx.MockRouter
) -> None:
    route = api.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    response = client.post("/api/sources/test", json=HTTP_SOURCE)
    body = response.json()
    assert route.calls.last.request.headers["Authorization"] == SECRET
    assert (body["ok"], body["records"], len(body["preview"])) == (True, 6, 3)
    first = body["preview"][0]
    assert (first["external_id"], first["ch"], first["operator"], first["product"]) == (
        "c1",
        "chat",
        "Оператор 1",
        "Карты",
    )
    assert first["sample"][0] == {"who": "client", "text": "Вопрос номер 1"}
    assert body["errors"] == ["bad: transcript (messages) должен быть списком реплик"]
    assert "agent.name" in body["paths"]
    assert client.get("/api/state").json()["dialogs"] == []
    assert "s3cr3t" not in response.text


def test_sync_adds_dialogs_with_their_source_and_logs_it(client: TestClient, api: respx.MockRouter) -> None:
    api.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    sid = client.post("/api/sources", json=HTTP_SOURCE).json()["id"]
    first = client.post(f"/api/sources/{sid}/sync").json()
    assert (first["status"], first["added"], first["skipped"]) == ("partial", 5, 1)
    again = client.post(f"/api/sources/{sid}/sync").json()
    assert (again["status"], again["added"], again["skipped"]) == ("partial", 0, 6)  # дубли по external_id
    dialogs = client.get("/api/state").json()["dialogs"]
    assert {(d["source_id"], d["external_id"]) for d in dialogs} == {("src1", f"c{n}") for n in range(1, 6)}
    assert dialogs[0]["title"] == "Чат c1"
    syncs = client.get(f"/api/sources/{sid}/syncs").json()
    assert [s["status"] for s in syncs] == ["partial", "partial"]
    assert syncs[0]["duration_ms"] is not None


def test_failed_sync_is_logged_and_makes_the_source_unhealthy(
    client: TestClient, api: respx.MockRouter
) -> None:
    api.get(API).mock(return_value=httpx.Response(500))
    sid = client.post("/api/sources", json=HTTP_SOURCE).json()["id"]
    row = client.post(f"/api/sources/{sid}/sync").json()
    assert (row["status"], row["errors"]) == ("error", ["источник ответил статусом 500"])
    stats = {s["id"]: s for s in client.get("/api/sources/stats").json()}
    assert stats[sid]["health"] == "error"
    assert stats[sid]["basis"] == "последняя синхронизация с ошибкой: источник ответил статусом 500"
    assert stats[sid]["error_rate"] == 1.0


def test_stats_count_dialogs_and_freshness_per_source(client: TestClient, api: respx.MockRouter) -> None:
    api.get(API).mock(return_value=httpx.Response(200, json={"data": {"items": [_chat(1)]}}))
    sid = client.post("/api/sources", json=HTTP_SOURCE).json()["id"]
    client.post(f"/api/sources/{sid}/sync")
    stats = {s["id"]: s for s in client.get("/api/sources/stats").json()}
    assert (stats[sid]["dialogs"], stats[sid]["scored"], stats[sid]["health"]) == (1, 0, "ok")
    assert stats[sid]["last_sync"]["status"] == "ok"
    assert stats[sid]["freshness_s"] is not None and stats[sid]["freshness_s"] < 60
    assert stats["org"]["basis"] == "источник выключен"


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9/x", "http://169.254.169.254/latest/meta-data", "https://intranet.test/x"]
)
def test_private_addresses_are_blocked(client: TestClient, api: respx.MockRouter, url: str) -> None:
    route = api.get(url).mock(return_value=httpx.Response(200, json=PAYLOAD))
    draft = {**HTTP_SOURCE, "config": {**HTTP_SOURCE["config"], "url": url}}  # type: ignore[dict-item]
    body = client.post("/api/sources/test", json=draft).json()
    assert body["ok"] is False
    assert "внутренней сети" in body["error"]
    assert not route.called


def test_private_addresses_are_allowed_by_the_setting(settings: Settings, api: respx.MockRouter) -> None:
    url = "http://127.0.0.1:9/x"
    api.get(url).mock(return_value=httpx.Response(200, json=PAYLOAD))
    draft = {**HTTP_SOURCE, "config": {**HTTP_SOURCE["config"], "url": url}}  # type: ignore[dict-item]
    assert _app(settings, allow_private=True).post("/api/sources/test", json=draft).json()["ok"] is True


def test_redirects_are_not_followed(client: TestClient, api: respx.MockRouter) -> None:
    api.get(API).mock(return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/"}))
    body = client.post("/api/sources/test", json=HTTP_SOURCE).json()
    assert (body["ok"], body["error"]) == (
        False,
        "источник ответил перенаправлением 302: укажите конечный адрес",
    )


def _record(n: int) -> dict[str, Any]:
    return {**_chat(n), "type": "call"}


def test_webhook_token_is_shown_once_and_bearer_push_is_accepted(client: TestClient) -> None:
    created = client.post("/api/sources", json=WEBHOOK).json()
    token, sid = created["token"], created["id"]
    assert created["ingest_path"] == f"/api/sources/{sid}/ingest"
    assert token not in client.get("/api/sources").text
    pushed = client.post(
        f"/api/sources/{sid}/ingest",
        json=[_record(1), _record(2)],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pushed.status_code == 200
    assert pushed.json() == {"added": 2, "skipped": 0, "errors": []}
    one = client.post(
        f"/api/sources/{sid}/ingest", json=_record(3), headers={"Authorization": f"Bearer {token}"}
    )
    assert one.json()["added"] == 1  # один объект — одна запись
    assert client.get(f"/api/sources/{sid}/syncs").json()[0]["status"] == "ok"
    calls = [d for d in client.get("/api/state").json()["dialogs"] if d["source_id"] == sid]
    assert [d["ch"] for d in calls] == ["call", "call", "call"]


def test_webhook_rejects_a_wrong_token_and_a_disabled_source(client: TestClient) -> None:
    created = client.post("/api/sources", json=WEBHOOK).json()
    sid = created["id"]
    wrong = client.post(f"/api/sources/{sid}/ingest", json=[], headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert client.post(f"/api/sources/{sid}/ingest", json=[]).status_code == 401
    client.put(f"/api/sources/{sid}", json={**WEBHOOK, "enabled": False})
    off = client.post(
        f"/api/sources/{sid}/ingest", json=[], headers={"Authorization": f"Bearer {created['token']}"}
    )
    assert off.status_code == 409


def test_webhook_with_hmac_signature(client: TestClient) -> None:
    created = client.post(
        "/api/sources", json={**WEBHOOK, "config": {"mapping": MAPPING, "auth": "hmac"}}
    ).json()
    raw = json.dumps([_record(1)]).encode()
    sig = hmac.new(created["token"].encode(), raw, hashlib.sha256).hexdigest()
    url = f"/api/sources/{created['id']}/ingest"
    assert client.post(url, content=raw, headers={"X-CQA-Signature": f"sha256={sig}"}).json()["added"] == 1
    bad = client.post(url, content=raw, headers={"X-CQA-Signature": "sha256=00"})
    assert bad.status_code == 401


def test_webhook_works_behind_the_access_token(settings: Settings) -> None:
    locked = settings.model_copy(update={"access_token": SecretStr("lan-token")})
    client = TestClient(
        create_app(locked, source=FakeSource(), evaluator=FakeEvaluator(), conn=connect(":memory:"))
    )
    client.get("/login?token=lan-token")
    created = client.post("/api/sources", json=WEBHOOK).json()
    client.cookies.clear()
    pushed = client.post(
        f"/api/sources/{created['id']}/ingest",
        json=[_record(1)],
        headers={"Authorization": f"Bearer {created['token']}"},
    )
    assert pushed.status_code == 200
    assert client.get("/api/sources").status_code == 401


def test_webhook_test_previews_a_pasted_sample(client: TestClient) -> None:
    sid = client.post("/api/sources", json=WEBHOOK).json()["id"]
    body = client.post(f"/api/sources/{sid}/test", json={"sample": [_record(1)]}).json()
    assert (body["ok"], body["preview"][0]["ch"]) == (True, "call")
    assert client.post(f"/api/sources/{sid}/test", json={}).status_code == 422


def test_delete_needs_archive_when_dialogs_exist(client: TestClient) -> None:
    created = client.post("/api/sources", json=WEBHOOK).json()
    sid = created["id"]
    client.post(
        f"/api/sources/{sid}/ingest",
        json=[_record(1)],
        headers={"Authorization": f"Bearer {created['token']}"},
    )
    assert client.delete(f"/api/sources/{sid}").status_code == 409
    assert client.delete(f"/api/sources/{sid}?archive=true").json() == {"archived": sid}
    archived = next(s for s in client.get("/api/sources").json() if s["id"] == sid)
    assert (archived["archived"], archived["enabled"]) == (True, False)
    empty = client.post("/api/sources", json=WEBHOOK).json()["id"]
    assert client.delete(f"/api/sources/{empty}").json() == {"deleted": empty}
    assert client.delete("/api/sources/file").status_code == 409


def test_update_keeps_the_saved_secret_when_empty(client: TestClient, api: respx.MockRouter) -> None:
    route = api.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    sid = client.post("/api/sources", json=HTTP_SOURCE).json()["id"]
    updated = client.put(f"/api/sources/{sid}", json={**HTTP_SOURCE, "name": "Чат 2", "secret": ""}).json()
    assert (updated["name"], updated["has_secret"]) == ("Чат 2", True)
    client.post(f"/api/sources/{sid}/sync")
    assert route.calls.last.request.headers["Authorization"] == SECRET


def test_org_api_needs_an_https_link_to_be_enabled(client: TestClient) -> None:
    org = {"name": "Организаторы", "kind": "org_api", "config": {"group_id": "DEV"}, "enabled": True}
    response = client.put("/api/sources/org", json=org)
    assert response.status_code == 422
    assert set(response.json()["fields"]) == {"secret"}
    plain = client.put("/api/sources/org", json={**org, "secret": "http://org.test/api"})
    assert "https://" in plain.json()["fields"]["secret"]


def test_file_upload_and_paste_are_accounted_to_builtin_sources(client: TestClient) -> None:
    client.post(
        "/api/dialogs/text",
        json={"title": "", "ch": "chat", "text": "Клиент: привет\nОператор: здравствуйте"},
    )
    (row,) = client.get("/api/sources/paste/syncs").json()
    assert (row["status"], row["added"]) == ("ok", 1)
    assert client.get("/api/state").json()["dialogs"][0]["source_id"] == "paste"
    assert client.post("/api/sources/paste/sync").status_code == 422


def test_report_has_a_by_source_section(client: TestClient) -> None:
    client.post(
        "/api/dialogs/text",
        json={"title": "", "ch": "chat", "text": "Клиент: привет\nОператор: здравствуйте"},
    )
    assert client.get("/api/report?format=json").json()["sources"] == []  # не оценён — в разделе нет
    assert client.get("/api/report?format=json&source=paste").json()["summary"]["dialogs"] == 1
    assert {s["id"] for s in client.get("/api/state").json()["sources"]} >= {"org", "file", "paste", "api"}
