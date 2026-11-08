"""Пакетная обработка: `/api/batches` (design/contract.md, «Пакетная обработка»)."""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from cqa.services.batches import Action, Batches

router = APIRouter(prefix="/api")


class BatchFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")  # неизвестное поле фильтра — 422, а не молча «все диалоги»
    source_id: str | None = None
    ch: Literal["chat", "call"] | None = None
    lang: str | None = None
    product: str | None = None
    since: date | None = None
    unscored_only: bool = True


class BatchIn(BaseModel):
    dialogs: list[str] | None = None
    filter: BatchFilter | None = None
    batch_size: int = Field(20, ge=1, le=200)
    priority: Literal["high", "normal", "low"] = "normal"
    force: bool = False


def _batches(request: Request) -> Batches:
    batches: Batches = request.app.state.batches
    return batches


def _rate_limit(request: Request) -> dict[str, int]:
    settings = request.app.state.settings
    return {"rpm": settings.llm_rpm, "parallel": settings.llm_max_parallel}


@router.post("/batches")
async def post_batch(body: BatchIn, request: Request) -> dict[str, Any]:
    flt = body.filter.model_dump(exclude_unset=True) if body.filter is not None else None
    job = _batches(request).create(
        body.dialogs, flt, batch_size=body.batch_size, priority=body.priority, force=body.force
    )
    return {**job, "rate_limit": _rate_limit(request)}


@router.get("/batches")
async def get_batches(request: Request) -> dict[str, Any]:
    return {"jobs": _batches(request).summaries(), "rate_limit": _rate_limit(request)}


@router.get("/batches/{job_id}")
async def get_batch(job_id: int, request: Request) -> dict[str, Any]:
    return {**_batches(request).view(job_id), "rate_limit": _rate_limit(request)}


@router.post("/batches/{job_id}/{action}")
async def post_batch_action(job_id: int, action: Action, request: Request) -> dict[str, Any]:
    return {**_batches(request).act(job_id, action), "rate_limit": _rate_limit(request)}
