"""FastAPI application factory (design/ports.md, "create_app и app.state")."""

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cqa.services.ports import DialogSource, Evaluator
from cqa.settings import Settings

WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def create_app(
    settings: Settings | None = None,
    *,
    source: DialogSource | None = None,
    evaluator: Evaluator | None = None,
    conn: sqlite3.Connection | None = None,
) -> FastAPI:
    app = FastAPI(title="CQA")
    app.state.settings = settings or Settings()

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    # routers of the tracks go here (review-workflow: cqa.http.api, dialog-ingest: cqa.http.audio)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")  # last: it shadows every path
    return app
