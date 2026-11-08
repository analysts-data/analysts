"""FastAPI application factory (design/ports.md, "create_app и app.state")."""

import asyncio
import contextlib
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cqa.adapters.store import Store, connect
from cqa.adapters.voice import PraatVoice
from cqa.compose import build_evaluator, build_source
from cqa.domain.models import Checklist
from cqa.http import api, docs
from cqa.http.access import protect
from cqa.http.audio import router as audio_router
from cqa.services.errors import Conflict, Invalid, NotFound, Unavailable, Upstream
from cqa.services.llm_config import effective
from cqa.services.ports import DialogSource, Evaluator
from cqa.services.prosody import dialog_prosody
from cqa.services.runs import Runner
from cqa.services.state import mode_from_settings
from cqa.services.sync import Syncer
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


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Автосинхронизация набора организаторов, пока работает сервер."""
    syncer: Syncer | None = app.state.syncer
    task = asyncio.create_task(syncer.run()) if syncer else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _detail(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        {"detail": str(exc)}, status_code=next(c for t, c in STATUS.items() if isinstance(exc, t))
    )


def seed_checklist(store: Store) -> None:
    """Начальный чек-лист на пустой базе: первый запуск сервера или scripts/results.py --evaluate."""
    if store.current_checklist() is None:
        store.add_checklist(
            Checklist.model_validate_json(SEED_CHECKLIST.read_text(encoding="utf-8")), "начальная версия"
        )


def create_app(
    settings: Settings | None = None,
    *,
    source: DialogSource | None = None,
    evaluator: Evaluator | None = None,
    conn: sqlite3.Connection | None = None,
) -> FastAPI:
    # свой /docs/ без CDN вместо Swagger и ReDoc; схема OpenAPI рядом с остальным API
    app = FastAPI(
        title="CQA", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json"
    )
    # встраивание в Dynamics 365: источник — домен тенанта, без cookies; чтение и запуск оценки
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https://[a-z0-9-]+(\.[a-z0-9-]+)*\.dynamics\.com",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )
    settings = settings or Settings()
    app.state.settings = settings
    if settings.access_token:
        protect(app, settings.access_token.get_secret_value())
    for exc_class in STATUS:
        app.add_exception_handler(exc_class, _detail)

    @app.get("/api/health", summary="Проверка, что сервер работает")
    def health() -> dict[str, bool]:
        return {"ok": True}

    store = Store(conn if conn is not None else connect(settings.db_path))
    settings = app.state.settings = effective(settings, store.overrides())  # режим из интерфейса поверх .env
    store.cancel_stale_runs()
    seed_checklist(store)
    app.state.store = store
    app.state.source = source if source is not None else build_source(settings)
    app.state.syncer = Syncer(store, app.state.source)
    app.state.voice = PraatVoice(httpx.AsyncClient())  # интонация: запись скачивается и разбирается локально

    async def prosody(dialog_id: str) -> dict[str, Any]:
        """Порт `Prosody` оценщика: source и voice читаются из app.state при вызове, как у `/prosody`."""
        return await dialog_prosody(store, app.state.source, app.state.voice, dialog_id)

    app.state.prosody = prosody
    evaluator = evaluator if evaluator is not None else build_evaluator(settings, prosody)  # llm-evaluation
    app.state.runner = Runner(store, evaluator, parallel=settings.llm_max_parallel)
    app.state.mode = mode_from_settings(settings)

    app.include_router(api.router)
    app.include_router(audio_router)
    app.include_router(docs.router)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")  # last: it shadows every path
    return app
