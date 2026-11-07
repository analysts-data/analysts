"""Contract paths of design/contract.md except /audio and /player. Handlers are async: one SQLite
connection, used only from the event loop thread (review-workflow design, decision 17)."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from cqa.services.dialogs import set_reviewed
from cqa.services.state import build_state

router = APIRouter(prefix="/api")


class ReviewedIn(BaseModel):
    reviewed: bool


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    return build_state(request.app.state.store, request.app.state.mode)


@router.post("/dialogs/{dialog_id}/reviewed")
async def post_reviewed(dialog_id: str, body: ReviewedIn, request: Request) -> dict[str, bool]:
    set_reviewed(request.app.state.store, dialog_id, body.reviewed)
    return {"ok": True}
