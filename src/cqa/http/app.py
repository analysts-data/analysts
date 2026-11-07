"""FastAPI application factory (design/ports.md, "create_app и app.state")."""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cqa.services.errors import Conflict, Invalid, NotFound, Unavailable, Upstream
from cqa.services.ports import DialogSource, Evaluator
from cqa.settings import Settings

WEB_DIR = Path(__file__).resolve().parents[3] / "web"
STATUS: dict[type[Exception], int] = {
    NotFound: 404,
    Invalid: 422,
    Conflict: 409,
    Upstream: 502,
    Unavailable: 503,
}


async def _detail(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        {"detail": str(exc)}, status_code=next(c for t, c in STATUS.items() if isinstance(exc, t))
    )


def create_app(
    settings: Settings | None = None,
    *,
    source: DialogSource | None = None,
    evaluator: Evaluator | None = None,
    conn: sqlite3.Connection | None = None,
) -> FastAPI:
    app = FastAPI(title="CQA")
    app.state.settings = settings or Settings()
    for exc_class in STATUS:
        app.add_exception_handler(exc_class, _detail)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    # routers of the tracks go here (review-workflow: cqa.http.api, dialog-ingest: cqa.http.audio)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")  # last: it shadows every path
    return app
