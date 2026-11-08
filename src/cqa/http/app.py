"""FastAPI application factory (design/ports.md, "create_app и app.state")."""

import asyncio
import contextlib
import json
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cqa.adapters import webhook
from cqa.adapters.batches import BatchStore
from cqa.adapters.http_source import HttpSource
from cqa.adapters.store import Store, connect
from cqa.adapters.voice import PraatVoice
from cqa.compose import build_classifier, build_routed, build_source
from cqa.domain.models import Checklist, Product
from cqa.domain.review import ASTANA
from cqa.http import api, batches, docs, sources
from cqa.http.access import protect
from cqa.http.audio import router as audio_router
from cqa.services.alerts import refresh
from cqa.services.automation import Automation, wire
from cqa.services.batches import Batches
from cqa.services.checklists import SEED_CHECKLIST
from cqa.services.errors import Conflict, Invalid, NotFound, Unauthorized, Unavailable, Upstream
from cqa.services.llm_config import effective
from cqa.services.ports import DialogSource, Evaluator
from cqa.services.prosody import dialog_prosody
from cqa.services.runs import Classifier, Runner
from cqa.services.state import mode_from_settings
from cqa.services.sync import Syncer
from cqa.services.telemetry import TokenBucket, purge
from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT / "web"
SEED_PRODUCTS = ROOT / "tests" / "fixtures" / "products.json"  # справочник тем — данные, как чек-лист
STATUS: dict[type[Exception], int] = {
    NotFound: 404,
    Invalid: 422,
    Unauthorized: 401,
    Conflict: 409,
    Upstream: 502,
    Unavailable: 503,
}


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Автосинхронизация набора организаторов, очередь батчей и планировщик автоматизации."""
    syncer: Syncer = app.state.syncer
    automation: Automation = app.state.automation
    tasks = [
        asyncio.create_task(app.state.batches.work()),
        asyncio.create_task(syncer.run(skip=automation.owns_sync)),
        asyncio.create_task(automation.run()),
    ]
    yield
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _detail(request: Request, exc: Exception) -> JSONResponse:
    body: dict[str, Any] = {"detail": str(exc)}
    if isinstance(exc, Invalid) and exc.fields:
        body["fields"] = exc.fields  # ошибки по полям формы источника
    return JSONResponse(body, status_code=next(c for t, c in STATUS.items() if isinstance(exc, t)))


def seed_checklist(store: Store) -> None:
    """Начальный чек-лист на пустой базе: первый запуск сервера или scripts/results.py --evaluate."""
    if store.current_checklist() is None:
        store.add_checklist(
            Checklist.model_validate_json(SEED_CHECKLIST.read_text(encoding="utf-8")), "начальная версия"
        )


def seed_products(store: Store) -> None:
    """Начальный справочник тем обращений на пустой базе."""
    if store.products() is None:
        raw = json.loads(SEED_PRODUCTS.read_text(encoding="utf-8"))
        store.set_products([Product.model_validate(p) for p in raw])


def create_app(
    settings: Settings | None = None,
    *,
    source: DialogSource | None = None,
    evaluator: Evaluator | None = None,
    conn: sqlite3.Connection | None = None,
    classifier: Classifier | None = None,
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
        allow_headers=["Content-Type", "X-CQA-User"],  # X-CQA-User — текущий сотрудник
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

    conn = conn if conn is not None else connect(settings.db_path)
    store = Store(conn)
    settings = app.state.settings = effective(settings, store.overrides())  # режим из интерфейса поверх .env
    store.cancel_stale_runs()
    store.clear_pending_products()
    purge(store, settings.telemetry_retention_days, datetime.now(UTC))
    seed_checklist(store)
    seed_products(store)
    app.state.store = store
    app.state.source = source if source is not None else build_source(settings)
    store.fail_stale_syncs()
    http_source = HttpSource(httpx.AsyncClient(), allow_private=settings.allow_private_sources)
    app.state.syncer = Syncer(store, app.state.source, http_source, settings)
    app.state.voice = PraatVoice(httpx.AsyncClient())  # интонация: запись скачивается и разбирается локально

    async def prosody(dialog_id: str) -> dict[str, Any]:
        """Порт `Prosody` оценщика: source и voice читаются из app.state при вызове, как у `/prosody`."""
        return await dialog_prosody(store, app.state.source, app.state.voice, dialog_id)

    app.state.prosody = prosody
    # ponytail: вебхук ждём в самом запросе; очередь — если получатель окажется медленным
    hooks = httpx.AsyncClient(timeout=5)

    async def alerts() -> list[dict[str, Any]]:
        """Проверить правила алертов и отправить новые как `alert.created` (вебхук только при настройке)."""
        created = refresh(store, datetime.now(ASTANA))
        s = app.state.settings
        if s.webhook_url and created:
            secret = s.webhook_secret.get_secret_value() if s.webhook_secret else None
            await webhook.send(hooks, s.webhook_url, secret, "alert.created", created)
        return created

    app.state.alerts = alerts
    if evaluator is None:  # llm-evaluation; подставленный оценщик (тесты) — без своего классификатора тем
        evaluator = build_routed(settings, prosody, store)
        classifier = classifier if classifier is not None else build_classifier(settings)
    app.state.runner = Runner(
        store, evaluator, parallel=settings.llm_max_parallel, on_finish=alerts, classifier=classifier
    )
    app.state.batches = Batches(store, BatchStore(conn), app.state.runner)
    app.state.batches.recover()  # незаконченные задания прошлого процесса — на паузу с пояснением
    app.state.mode = mode_from_settings(settings)
    # выключена по умолчанию: пока enabled false, планировщик только читает настройки
    app.state.automation = Automation(
        store, wire(store, app.state.syncer, app.state.runner, app.state.batches, prosody)
    )
    app.state.telemetry_limit = TokenBucket(capacity=30, rate=0.5)  # ~1 пакет в 2 с на клиента

    app.include_router(api.router)
    app.include_router(sources.router)
    app.include_router(batches.router)
    app.include_router(audio_router)
    app.include_router(docs.router)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")  # last: it shadows every path
    return app
