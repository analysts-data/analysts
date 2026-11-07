"""Contract paths of design/contract.md except /audio and /player. Handlers are async: one SQLite
connection, used only from the event loop thread (review-workflow design, decision 17)."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from cqa.domain.models import Appeal, Checklist
from cqa.domain.review import ASTANA
from cqa.services.appeals import decide, file_appeal, record_review
from cqa.services.checklists import save_checklist
from cqa.services.datasets import load_group, load_upload
from cqa.services.dialogs import save_owners, set_reviewed
from cqa.services.errors import Unavailable
from cqa.services.ports import DialogSource
from cqa.services.runs import Runner
from cqa.services.state import build_state
from cqa.services.sync import Syncer

router = APIRouter(prefix="/api")

Owner = Literal["Не назначено", "Инструкция", "Сервис", "Продукт"]


class ReviewedIn(BaseModel):
    reviewed: bool


class DatasetIn(BaseModel):
    group_id: str


class SourceIn(BaseModel):
    url: str
    group_id: str


class RunIn(BaseModel):
    dialogs: list[str] | None = None  # порядок очереди: диалоги для демо первыми
    criteria: list[str] | None = None


def _runner(request: Request) -> Runner:
    runner: Runner | None = request.app.state.runner
    if runner is None:
        raise Unavailable("Оценка моделью не подключена")
    return runner


def _source(request: Request) -> DialogSource:
    source: DialogSource | None = request.app.state.source
    if source is None:
        raise Unavailable("Загрузка наборов не подключена")
    return source


def _syncer(request: Request) -> Syncer:
    syncer: Syncer | None = request.app.state.syncer
    if syncer is None:
        raise Unavailable("Загрузка наборов не подключена")
    return syncer


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    syncer: Syncer | None = request.app.state.syncer
    state = build_state(request.app.state.store, request.app.state.mode)
    return {**state, "source": syncer.status() if syncer else None}


@router.post("/dialogs/{dialog_id}/reviewed")
async def post_reviewed(dialog_id: str, body: ReviewedIn, request: Request) -> dict[str, bool]:
    set_reviewed(request.app.state.store, dialog_id, body.reviewed)
    return {"ok": True}


@router.put("/checklist")
async def put_checklist(draft: Checklist, request: Request) -> dict[str, Any]:
    return save_checklist(request.app.state.store, draft)


@router.put("/owners")
async def put_owners(body: dict[str, Owner], request: Request) -> dict[str, str]:
    return save_owners(request.app.state.store, body)


class AppealIn(BaseModel):
    dlg: str
    cid: str
    ask: str | int
    ev: list[int] = []
    comment: str
    by: str


class DecisionIn(BaseModel):
    to: str | int
    reason: str
    reviewer: str


class ReviewIn(BaseModel):
    dlg: str
    cid: str
    from_: str | int = Field(alias="from")
    to: str | int
    reason: str
    reviewer: str


def _appeal_out(appeal: Appeal) -> dict[str, Any]:
    return appeal.model_dump(mode="json", by_alias=True, exclude={"ask"} if appeal.kind == "review" else None)


@router.post("/appeals")
async def post_appeal(body: AppealIn, request: Request) -> dict[str, Any]:
    appeal = file_appeal(request.app.state.store, **body.model_dump(), now=datetime.now(ASTANA))
    return _appeal_out(appeal)


@router.post("/appeals/{appeal_id}/decision")
async def post_decision(appeal_id: str, body: DecisionIn, request: Request) -> dict[str, Any]:
    appeal = decide(request.app.state.store, appeal_id, **body.model_dump(), now=datetime.now(ASTANA))
    return _appeal_out(appeal)


@router.post("/decisions")
async def post_review(body: ReviewIn, request: Request) -> dict[str, Any]:
    fields = body.model_dump(exclude={"from_"})
    record = record_review(request.app.state.store, frm=body.from_, **fields, now=datetime.now(ASTANA))
    return _appeal_out(record)


@router.post("/datasets")
async def post_dataset(body: DatasetIn, request: Request) -> dict[str, int]:
    return await load_group(request.app.state.store, _source(request), body.group_id)


@router.put("/source")
async def put_source(body: SourceIn, request: Request) -> dict[str, int]:
    """Ссылка API организаторов из интерфейса: сразу загрузка набора, затем автосинхронизация."""
    return await _syncer(request).configure(body.url, body.group_id)


@router.post("/datasets/upload")
async def post_upload(request: Request) -> dict[str, int]:
    """Сырое тело файла: без `UploadFile` и зависимости `python-multipart`."""
    return load_upload(request.app.state.store, _source(request), await request.body())


@router.post("/runs")
async def post_run(body: RunIn, request: Request) -> dict[str, int]:
    return {"run_id": _runner(request).start(body.dialogs, body.criteria)}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, request: Request) -> dict[str, Any]:
    return _runner(request).progress(run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, request: Request) -> dict[str, str]:
    return _runner(request).cancel(run_id)
