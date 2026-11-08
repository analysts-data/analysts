"""Источники диалогов (design/contract.md, «Источники»): реестр, проверка, синхронизация, webhook, учёт."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from cqa.services.errors import Unavailable
from cqa.services.sources import (
    create_source,
    delete_source,
    get_source,
    ingest_push,
    list_sources,
    source_stats,
    source_syncs,
    update_source,
)
from cqa.services.sync import Syncer

router = APIRouter(prefix="/api")


class SourceIn(BaseModel):
    name: str
    kind: Literal["org_api", "http_json", "webhook", "file", "paste", "api"]
    service: str = ""
    channel_default: Literal["chat", "call"] | None = None
    product_default: str | None = None
    config: dict[str, Any] = {}
    secret: str = ""  # только запись: пусто — оставить сохранённый
    enabled: bool = True
    schedule_min: int = 0
    rotate_token: bool = False  # webhook: выдать новый токен (ответ покажет его один раз)


class DraftTestIn(SourceIn):
    sample: Any = None  # webhook: пример тела запроса


class TestIn(BaseModel):
    sample: Any = None


def _syncer(request: Request) -> Syncer:
    syncer: Syncer | None = request.app.state.syncer
    if syncer is None:
        raise Unavailable("Загрузка наборов не подключена")
    return syncer


@router.get("/sources")
async def get_sources(request: Request) -> list[dict[str, Any]]:
    return list_sources(request.app.state.store)


@router.get("/sources/stats")
async def get_source_stats(request: Request) -> list[dict[str, Any]]:
    return source_stats(request.app.state.store, datetime.now(UTC))


@router.post("/sources")
async def post_source(body: SourceIn, request: Request) -> dict[str, Any]:
    return create_source(request.app.state.store, body.model_dump())


@router.post("/sources/test")
async def post_source_draft_test(body: DraftTestIn, request: Request) -> dict[str, Any]:
    """Мастер добавления: связь и предпросмотр до сохранения, ничего не пишет."""
    return await _syncer(request).test_draft(body.model_dump(exclude={"sample"}), body.sample)


@router.put("/sources/{source_id}")
async def put_source_route(source_id: str, body: SourceIn, request: Request) -> dict[str, Any]:
    return update_source(request.app.state.store, source_id, body.model_dump())


@router.delete("/sources/{source_id}")
async def delete_source_route(source_id: str, request: Request, archive: bool = False) -> dict[str, Any]:
    return delete_source(request.app.state.store, source_id, archive=archive)


@router.post("/sources/{source_id}/test")
async def post_source_test(source_id: str, request: Request, body: TestIn | None = None) -> dict[str, Any]:
    src = get_source(request.app.state.store, source_id)
    return await _syncer(request).test(src, body.sample if body else None)


@router.post("/sources/{source_id}/sync")
async def post_source_sync(source_id: str, request: Request) -> dict[str, Any]:
    return await _syncer(request).sync_source(source_id)


@router.get("/sources/{source_id}/syncs")
async def get_source_syncs(source_id: str, request: Request, limit: int = 50) -> list[dict[str, Any]]:
    return source_syncs(request.app.state.store, source_id, min(max(limit, 1), 200))


@router.post("/sources/{source_id}/ingest")
async def post_source_ingest(source_id: str, request: Request) -> dict[str, Any]:
    """Webhook внешнего сервиса: `Authorization: Bearer <токен>` или `X-CQA-Signature: sha256=<hmac>`."""
    state = request.app.state
    raw = await request.body()
    return ingest_push(state.store, state.settings, source_id, raw, request.headers, datetime.now(UTC))

