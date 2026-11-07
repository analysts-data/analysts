"""Contract paths of design/contract.md except /audio and /player. Handlers are async: one SQLite
connection, used only from the event loop thread (review-workflow design, decision 17)."""

from typing import Any

from fastapi import APIRouter, Request

from cqa.services.state import build_state

router = APIRouter(prefix="/api")


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    return build_state(request.app.state.store, request.app.state.mode)
