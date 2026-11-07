"""FastAPI application factory (design/ports.md, "create_app и app.state")."""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cqa.adapters.store import Store, connect
from cqa.compose import build_source
from cqa.domain.models import Checklist
from cqa.http import api
from cqa.http.audio import router as audio_router
from cqa.services.errors import Conflict, Invalid, NotFound, Unavailable, Upstream
from cqa.services.ports import DialogSource, Evaluator
from cqa.services.runs import Runner
from cqa.services.state import mode_from_settings
from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT / "web"
# ponytail: seed is the test fixture; a separate product file if the two ever diverge
SEED_CHECKLIST = ROOT / "tests" / "fixtures" / "checklist_v3.json"
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
    settings = settings or Settings()
    app.state.settings = settings
    for exc_class in STATUS:
        app.add_exception_handler(exc_class, _detail)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    store = Store(conn if conn is not None else connect(settings.db_path))
    store.cancel_stale_runs()
    if store.current_checklist() is None:
        store.add_checklist(
            Checklist.model_validate_json(SEED_CHECKLIST.read_text(encoding="utf-8")), "начальная версия"
        )
    app.state.store = store
    app.state.source = source if source is not None else build_source(settings)
    app.state.runner = (
        Runner(store, evaluator, parallel=settings.llm_max_parallel) if evaluator is not None else None
    )
    app.state.mode = mode_from_settings(settings)

    app.include_router(api.router)
    app.include_router(audio_router)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")  # last: it shadows every path
    return app
