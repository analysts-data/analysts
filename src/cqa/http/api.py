"""Contract paths of design/contract.md except /audio and /player. Handlers are async: one SQLite
connection, used only from the event loop thread (review-workflow design, decision 17)."""

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from cqa.services.datasets import load_group, load_upload
from cqa.services.dialogs import save_owners, set_reviewed
from cqa.services.errors import Unavailable
from cqa.services.ports import DialogSource
from cqa.services.state import build_state

router = APIRouter(prefix="/api")

Owner = Literal["Не назначено", "Инструкция", "Сервис", "Продукт"]


class ReviewedIn(BaseModel):
    reviewed: bool


class DatasetIn(BaseModel):
    group_id: str


def _source(request: Request) -> DialogSource:
    source: DialogSource | None = request.app.state.source
    if source is None:
        raise Unavailable("Загрузка наборов не подключена")
    return source


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    return build_state(request.app.state.store, request.app.state.mode)


@router.post("/dialogs/{dialog_id}/reviewed")
async def post_reviewed(dialog_id: str, body: ReviewedIn, request: Request) -> dict[str, bool]:
    set_reviewed(request.app.state.store, dialog_id, body.reviewed)
    return {"ok": True}


@router.put("/owners")
async def put_owners(body: dict[str, Owner], request: Request) -> dict[str, str]:
    return save_owners(request.app.state.store, body)


@router.post("/datasets")
async def post_dataset(body: DatasetIn, request: Request) -> dict[str, int]:
    return await load_group(request.app.state.store, _source(request), body.group_id)


@router.post("/datasets/upload")
async def post_upload(request: Request) -> dict[str, int]:
    """Сырое тело файла: без `UploadFile` и зависимости `python-multipart`."""
    return load_upload(request.app.state.store, _source(request), await request.body())
