"""Contract paths of design/contract.md except /audio and /player. Handlers are async: one SQLite
connection, used only from the event loop thread (review-workflow design, decision 17)."""

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import unquote

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StrictBool

from cqa.compose import build_evaluator, check_provider
from cqa.domain.models import Answer, Appeal, Checklist
from cqa.domain.review import ASTANA
from cqa.services import alerts
from cqa.services.answers import set_answer
from cqa.services.appeals import decide, file_appeal, record_review
from cqa.services.checklists import (
    DiffFormat,
    ExportFormat,
    diff_draft,
    diff_versions,
    export_checklist,
    save_checklist,
)
from cqa.services.datasets import load_group, load_upload
from cqa.services.dialogs import paste_text, save_owners, set_reviewed
from cqa.services.errors import Unavailable
from cqa.services.llm_config import Apply, configure, delete_provider, provider, put_provider, view
from cqa.services.ports import DialogSource
from cqa.services.runs import Runner
from cqa.services.state import ReportFormat, build_state, mode_from_settings, report
from cqa.services.sync import Syncer
from cqa.settings import Settings

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

Owner = Literal["Не назначено", "Инструкция", "Сервис", "Продукт"]
# ответ bool или scale; флаг — объект {"<k>": true | false}, строгие bool: 0 и "false" дают 422
AppealValue = str | int | dict[str, StrictBool]


class ReviewedIn(BaseModel):
    reviewed: bool


class PasteIn(BaseModel):
    title: str
    ch: Literal["chat", "call"]
    text: str


class DatasetIn(BaseModel):
    group_id: str


class SourceIn(BaseModel):
    url: str
    group_id: str


class AnswerIn(BaseModel):
    a: Answer
    reason: str = ""
    by: str


class ConfigIn(BaseModel):
    llm_provider: str
    anonymize: bool
    verifier: str | None = None  # "jev" или id провайдера
    evaluator: Literal["llm", "jev"] = "llm"
    jev_api_key: str = ""  # пусто — оставить сохранённый ключ
    allow_real_data: bool


class ProviderIn(BaseModel):
    label: str
    base_url: str
    model: str
    profile: str = "plain"
    where: Literal["kz", "local", "external"]
    key: str = ""  # пусто — оставить сохранённый ключ


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


@router.get("/report")
async def get_report(
    request: Request,
    fmt: Annotated[ReportFormat, Query(alias="format")] = "html",
    lang: str | None = None,
    ch: Literal["chat", "call"] | None = None,
) -> Response:
    """Отчёт для руководства: html — для печати, json — числа для аналитики, md — для вики и почты."""
    body = report(request.app.state.store, fmt, lang=lang, ch=ch, now=datetime.now(ASTANA))
    return JSONResponse(body) if isinstance(body, dict) else Response(body, media_type=MEDIA[fmt])


@router.post("/dialogs/text")
async def post_paste(body: PasteIn, request: Request) -> dict[str, str]:
    return {"id": paste_text(request.app.state.store, title=body.title, ch=body.ch, text=body.text)}


@router.post("/dialogs/{dialog_id}/reviewed")
async def post_reviewed(dialog_id: str, body: ReviewedIn, request: Request) -> dict[str, bool]:
    set_reviewed(request.app.state.store, dialog_id, body.reviewed)
    return {"ok": True}


@router.put("/checklist")
async def put_checklist(draft: Checklist, request: Request) -> dict[str, Any]:
    return save_checklist(request.app.state.store, draft)


MEDIA = {"json": "application/json", "csv": "text/csv", "md": "text/markdown", "html": "text/html"}


@router.get("/checklist/export")
async def get_checklist_export(
    request: Request, v: int | None = None, fmt: Annotated[ExportFormat, Query(alias="format")] = "json"
) -> Response:
    """Файл версии v (без v — текущей); памятка html открывается во вкладке, остальное скачивается."""
    version, body = export_checklist(request.app.state.store, v, fmt)
    how = "inline" if fmt == "html" else "attachment"
    disposition = f'{how}; filename="checklist-v{version}.{fmt}"'
    return Response(body, media_type=MEDIA[fmt], headers={"Content-Disposition": disposition})


def _diff_out(result: dict[str, Any] | str) -> Response:
    return JSONResponse(result) if isinstance(result, dict) else Response(result, media_type=MEDIA["md"])


@router.get("/checklist/diff")
async def get_checklist_diff(
    request: Request,
    frm: Annotated[int, Query(alias="from")],
    to: int | None = None,
    fmt: Annotated[DiffFormat, Query(alias="format")] = "json",
) -> Response:
    return _diff_out(diff_versions(request.app.state.store, frm, to, fmt))


@router.post("/checklist/diff")
async def post_checklist_diff(
    draft: Checklist, request: Request, fmt: Annotated[DiffFormat, Query(alias="format")] = "json"
) -> Response:
    return _diff_out(diff_draft(request.app.state.store, draft, fmt))


@router.put("/owners")
async def put_owners(body: dict[str, Owner], request: Request) -> dict[str, str]:
    return save_owners(request.app.state.store, body)


class AppealIn(BaseModel):
    dlg: str
    cid: str
    ask: AppealValue
    ev: list[int] = []
    comment: str
    by: str


class DecisionIn(BaseModel):
    to: AppealValue
    reason: str
    reviewer: str


class ReviewIn(BaseModel):
    dlg: str
    cid: str
    from_: AppealValue = Field(alias="from")
    to: AppealValue
    reason: str
    reviewer: str


def _appeal_out(appeal: Appeal) -> dict[str, Any]:
    return appeal.model_dump(mode="json", by_alias=True, exclude={"ask"} if appeal.kind == "review" else None)


async def _after_change(request: Request) -> None:
    """Проверка алертов после апелляций и маркеров; её сбой не отменяет уже сохранённое действие."""
    try:
        await request.app.state.alerts()
    except Exception:
        log.exception("проверка алертов")


@router.post("/appeals")
async def post_appeal(body: AppealIn, request: Request) -> dict[str, Any]:
    appeal = file_appeal(request.app.state.store, **body.model_dump(), now=datetime.now(ASTANA))
    await _after_change(request)
    return _appeal_out(appeal)


@router.post("/appeals/{appeal_id}/decision")
async def post_decision(appeal_id: str, body: DecisionIn, request: Request) -> dict[str, Any]:
    appeal = decide(request.app.state.store, appeal_id, **body.model_dump(), now=datetime.now(ASTANA))
    await _after_change(request)
    return _appeal_out(appeal)


@router.post("/decisions")
async def post_review(body: ReviewIn, request: Request) -> dict[str, Any]:
    fields = body.model_dump(exclude={"from_"})
    record = record_review(request.app.state.store, frm=body.from_, **fields, now=datetime.now(ASTANA))
    await _after_change(request)
    return _appeal_out(record)


# --- маркеры и алерты ---

ROLE = "Специалист КК"


def _actor(request: Request, fallback: str) -> str:
    """Сотрудник из заголовка `X-CQA-User` (кириллица — percent-encoding), иначе подпись роли из тела."""
    return unquote(request.headers.get("X-CQA-User", "")).strip() or fallback


class MarkersIn(BaseModel):
    add: list[str] = []
    remove: list[str] = []
    by: str = ROLE


class ByIn(BaseModel):
    by: str = ROLE


class ResolveIn(ByIn):
    note: str = ""


class AssigneeIn(BaseModel):
    assignee: str | None


def _fields(result: tuple[object, list[dict[str, Any]]]) -> Response:
    """Ошибки по полям — 422 в форме ошибок FastAPI: {detail: [{loc, msg}]}."""
    ok, errors = result
    return JSONResponse({"detail": errors}, status_code=422) if errors else JSONResponse(ok)


@router.get("/markers/catalog")
async def get_catalog(request: Request) -> list[str]:
    return alerts.catalog(request.app.state.store)


@router.put("/markers/catalog")
async def put_catalog(raw: Annotated[Any, Body()], request: Request) -> Response:
    errors = alerts.check_catalog(raw)
    return _fields(([], errors) if errors else (alerts.put_catalog(request.app.state.store, raw), []))


@router.put("/dialogs/{dialog_id}/markers")
async def put_markers(dialog_id: str, body: MarkersIn, request: Request) -> dict[str, Any]:
    store, by = request.app.state.store, _actor(request, body.by)
    alerts.change_markers(store, dialog_id, add=body.add, remove=body.remove, by=by, now=datetime.now(ASTANA))
    await _after_change(request)
    return {"markers": alerts.markers_of(store, dialog_id)}


@router.get("/alerts/rules")
async def get_rules(request: Request) -> list[dict[str, Any]]:
    return alerts.rules_out(request.app.state.store)


@router.put("/alerts/rules")
async def put_rules(raw: Annotated[Any, Body()], request: Request) -> Response:
    return _fields(alerts.put_rules(request.app.state.store, raw))


@router.post("/alerts/evaluate")
async def post_evaluate(request: Request) -> dict[str, Any]:
    return {"created": await request.app.state.alerts()}


@router.get("/alerts")
async def get_alerts(
    request: Request,
    status: Literal["new", "ack", "resolved"] | None = None,
    severity: Literal["info", "warning", "critical"] | None = None,
) -> dict[str, Any]:
    return alerts.list_alerts(request.app.state.store, status, severity)


@router.post("/alerts/{alert_id}/ack")
async def post_ack(alert_id: int, body: ByIn, request: Request) -> dict[str, Any]:
    by = _actor(request, body.by)
    return alerts.move(request.app.state.store, alert_id, "ack", by=by, now=datetime.now(ASTANA))


@router.post("/alerts/{alert_id}/resolve")
async def post_resolve(alert_id: int, body: ResolveIn, request: Request) -> dict[str, Any]:
    store, by, now = request.app.state.store, _actor(request, body.by), datetime.now(ASTANA)
    return alerts.move(store, alert_id, "resolved", by=by, note=body.note, now=now)


@router.put("/alerts/{alert_id}/assignee")
async def put_assignee(alert_id: int, body: AssigneeIn, request: Request) -> dict[str, Any]:
    return alerts.assign(request.app.state.store, alert_id, body.assignee)


@router.put("/dialogs/{dialog_id}/answers/{cid}")
async def put_answer(dialog_id: str, cid: str, body: AnswerIn, request: Request) -> dict[str, Any]:
    result = set_answer(
        request.app.state.store, dlg=dialog_id, cid=cid, a=body.a, reason=body.reason, by=body.by
    )
    return result.model_dump(mode="json", exclude_none=True)


def _apply(request: Request) -> Apply:
    """Пересобрать оценщик и плашку `mode` без перезапуска; во время запуска — 409."""
    state = request.app.state

    def apply(settings: Settings) -> None:
        _runner(request).use(build_evaluator(settings, state.prosody))
        state.settings, state.mode = settings, mode_from_settings(settings)

    return apply


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    return view(request.app.state.settings)


@router.put("/config")
async def put_config(body: ConfigIn, request: Request) -> dict[str, Any]:
    state = request.app.state
    return view(configure(state.store, state.settings, body.model_dump(), _apply(request)))


@router.put("/providers/{provider_id}")
async def put_provider_route(provider_id: str, body: ProviderIn, request: Request) -> dict[str, Any]:
    state = request.app.state
    return view(put_provider(state.store, state.settings, provider_id, body.model_dump(), _apply(request)))


@router.delete("/providers/{provider_id}")
async def delete_provider_route(provider_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    return view(delete_provider(state.store, state.settings, provider_id, _apply(request)))


@router.post("/providers/{provider_id}/check")
async def check_provider_route(provider_id: str, request: Request) -> dict[str, Any]:
    return await check_provider(provider(request.app.state.settings, provider_id))


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
