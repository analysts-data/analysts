"""Contract paths of design/contract.md except /audio and /player. Handlers are async: one SQLite
connection, used only from the event loop thread (review-workflow design, decision 17)."""

import json
import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from cqa.compose import build_evaluator, build_routed, check_provider
from cqa.domain.analytics import Filters
from cqa.domain.models import Answer, Appeal, Checklist
from cqa.domain.review import ASTANA
from cqa.domain.scores_export import Shape
from cqa.domain.usage import TOKEN, Event
from cqa.http.actor import actor_from, signed
from cqa.services import reports
from cqa.services.analytics import analytics
from cqa.services.answers import set_answer
from cqa.services.appeals import decide, file_appeal, record_review
from cqa.services.audit import Actor, AuditFormat, audit_log, record
from cqa.services.checklists import (
    DiffFormat,
    ExportFormat,
    diff_draft,
    diff_versions,
    export_checklist,
    save_checklist,
)
from cqa.services.datasets import load_group, load_upload
from cqa.services.dialogs import import_operators, paste_text, save_owners, set_operator, set_reviewed
from cqa.services.employees import Role, import_csv, overview, put_employee
from cqa.services.errors import Invalid, Unavailable
from cqa.services.history import adopt, history, restore
from cqa.services.llm_config import (
    Apply,
    configure,
    delete_provider,
    provider,
    put_provider,
    run_settings,
    view,
)
from cqa.services.ports import DialogSource
from cqa.services.routing import explain, put_routing
from cqa.services.routing import view as routing_view
from cqa.services.runs import ApplyMode, Runner, compare_runs, list_runs
from cqa.services.state import (
    Audience,
    ReportFormat,
    build_state,
    mode_from_settings,
    operator_page,
    operator_rows,
    recommendations,
    report,
    scores_csv,
)
from cqa.services.sync import Syncer
from cqa.services.telemetry import UsageFormat, store_events, usage
from cqa.settings import Settings

router = APIRouter(prefix="/api")

Owner = Literal["Не назначено", "Инструкция", "Сервис", "Продукт"]
# ответ bool или scale; флаг — объект {"<k>": true | false}, строгие bool: 0 и "false" дают 422
AppealValue = str | int | dict[str, StrictBool]


class ReviewedIn(BaseModel):
    reviewed: bool


class OperatorIn(BaseModel):
    operator: str | None = Field(max_length=200)  # обязательное: null снимает назначение


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


class ExplainIn(BaseModel):
    dialog_id: str


class OverrideIn(BaseModel):
    """Перепроверка другой моделью: поля поверх текущего режима, неуказанное — как в режиме."""

    model_config = ConfigDict(extra="forbid")
    evaluator: Literal["llm", "jev"] | None = None
    llm_provider: str | None = None
    verifier: str | None = None  # "jev", код провайдера или null — без второго мнения


class RunIn(BaseModel):
    dialogs: list[str] | None = None  # порядок очереди: диалоги для демо первыми
    criteria: list[str] | None = None
    force: bool = False  # повторная проверка: заново и пары с ответом, кроме ручных и с апелляцией
    confirm: bool = False  # повторная проверка без списка dialogs больше CONFIRM_OVER диалогов
    apply: ApplyMode = "replace"  # compare — ответы теневые до adopt или restore
    override: OverrideIn | None = None


class AdoptIn(BaseModel):
    dialogs: list[str] | None = None
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


def _log(
    request: Request,
    action: str,
    target_type: str,
    target_id: object = "",
    details: dict[str, Any] | None = None,
    actor: Actor | None = None,
) -> None:
    """Строка журнала действий после удачного изменения или выгрузки (раздел «Журнал действий»)."""
    record(request.app.state.store, actor or actor_from(request), action, target_type, target_id, details)


@router.get("/state", summary="Состояние для интерфейса: чек-лист, версии, диалоги, апелляции, режим")
async def get_state(request: Request) -> dict[str, Any]:
    syncer: Syncer | None = request.app.state.syncer
    state = build_state(request.app.state.store, request.app.state.mode)
    return {**state, "source": syncer.status() if syncer else None}


@router.get("/report", summary="Отчёт для руководства: html, json или md")
async def get_report(
    request: Request,
    fmt: Annotated[ReportFormat, Query(alias="format")] = "html",
    lang: str | None = None,
    ch: Literal["chat", "call"] | None = None,
    operator: str | None = None,
) -> Response:
    """Отчёт для руководства: html — для печати, json — числа для аналитики, md — для вики и почты."""
    store = request.app.state.store
    body = report(store, fmt, lang=lang, ch=ch, now=datetime.now(ASTANA), operator=operator)
    _log(request, "export", "report", fmt, {"lang": lang, "ch": ch, "operator": operator})
    return _file(body, fmt, "report")


@router.get("/recommendations")
async def get_recommendations(
    request: Request,
    audience: Annotated[Audience, Query(alias="for")],
    operator: Annotated[str | None, Query(alias="id")] = None,
) -> dict[str, Any]:
    """Рекомендации оператору (id — имя), проверяющему, руководителю и автору чек-листа; без модели."""
    return recommendations(request.app.state.store, audience, operator)


AnalyticsName = Literal["trend", "heatmap", "drivers", "distribution", "crosstab", "appeals", "model"]
AnalyticsBy = Literal["day", "week", "operator", "product", "lang", "ch"]


@router.get("/analytics/{name}")
async def get_analytics(
    name: AnalyticsName,
    request: Request,
    by: AnalyticsBy | None = None,
    lang: str | None = None,
    ch: Literal["chat", "call"] | None = None,
    operator: str | None = None,
    product: str | None = None,
    since: date | None = None,
    until: date | None = None,
) -> dict[str, Any]:
    """Расширенная аналитика (design/contract.md, «Аналитика»): n, low_n и формулы в каждом ответе."""
    filters = Filters(lang=lang, ch=ch, operator=operator, product=product, since=since, until=until)
    return analytics(request.app.state.store, name, filters, by, datetime.now(ASTANA))


def _file(body: dict[str, Any] | str, fmt: str, name: str) -> Response:
    """json — ответ JSON; html открывается во вкладке, csv и md скачиваются файлом name.<fmt>."""
    if isinstance(body, dict):
        return JSONResponse(body)
    how = "inline" if fmt == "html" else "attachment"
    return Response(
        body, media_type=MEDIA[fmt], headers={"Content-Disposition": f'{how}; filename="{name}.{fmt}"'}
    )


@router.get("/reports")
async def get_reports(request: Request) -> list[dict[str, Any]]:
    """Каталог отчётов для страницы «Отчёты»."""
    routes = set(request.app.openapi()["paths"])  # пути всех роутеров; схема кэшируется
    return reports.catalogue(routes, request.app.state.settings.results_dir)


@router.get("/quality")
async def get_quality_runs(request: Request) -> list[dict[str, Any]]:
    return reports.quality_runs(request.app.state.settings.eval_reports_dir)


@router.get("/quality/{report_id}")
async def get_quality(
    report_id: str, request: Request, fmt: Annotated[reports.Format, Query(alias="format")] = "html"
) -> Response:
    state = request.app.state
    body = reports.quality(state.store, state.settings.eval_reports_dir, report_id, fmt)
    return _file(body, fmt, f"quality-{report_id}")


@router.get("/runs/{run_id}/report")
async def get_run_report(
    run_id: int, request: Request, fmt: Annotated[reports.Format, Query(alias="format")] = "html"
) -> Response:
    return _file(reports.run(request.app.state.store, run_id, fmt, time.time()), fmt, f"run-{run_id}")


@router.get("/results/{which}")
async def get_results(which: Literal["dev", "prod"], request: Request) -> FileResponse:
    """Файл организаторов results/<which>/results.json, собранный make results."""
    path = reports.results_file(request.app.state.settings.results_dir, which)
    return FileResponse(path, media_type="application/json", filename=f"results-{which}.json")


@router.get("/scores/export", summary="Оценки диалогов для Excel (CSV)")
async def get_scores_export(
    request: Request,
    fmt: Annotated[Literal["csv"], Query(alias="format")] = "csv",
    shape: Shape = "wide",
    lang: str | None = None,
    ch: Literal["chat", "call"] | None = None,
) -> Response:
    """Оценки для Excel: wide — строка на диалог, long — на пару диалог × критерий."""
    version, body = scores_csv(request.app.state.store, shape, lang=lang, ch=ch)
    _log(request, "export", "scores", version, {"shape": shape, "lang": lang, "ch": ch})
    return _file(body, fmt, f"cqa-scores-v{version}")


@router.post("/dialogs/text", summary="Добавить диалог из вставленного текста")
async def post_paste(body: PasteIn, request: Request) -> dict[str, str]:
    dialog_id = paste_text(request.app.state.store, title=body.title, ch=body.ch, text=body.text)
    _log(request, "dataset.paste", "dialog", dialog_id, {"ch": body.ch})
    return {"id": dialog_id}


@router.post("/dialogs/{dialog_id}/reviewed", summary="Отметить диалог проверенным или снять отметку")
async def post_reviewed(dialog_id: str, body: ReviewedIn, request: Request) -> dict[str, bool]:
    set_reviewed(request.app.state.store, dialog_id, body.reviewed)
    _log(request, "dialog.reviewed" if body.reviewed else "dialog.unreviewed", "dialog", dialog_id)
    return {"ok": True}


@router.put("/dialogs/{dialog_id}/operator")
async def put_operator(dialog_id: str, body: OperatorIn, request: Request) -> dict[str, str | None]:
    return {"operator": set_operator(request.app.state.store, dialog_id, body.operator)}


@router.post("/operators/import")
async def post_operators_import(request: Request) -> dict[str, object]:
    """Сырое тело CSV, как у `/datasets/upload`: файл или вставленный текст."""
    return import_operators(request.app.state.store, await request.body())


@router.get("/operators")
async def get_operators(request: Request) -> dict[str, Any]:
    return operator_rows(request.app.state.store)


@router.get("/operators/{name:path}")
async def get_operator(name: str, request: Request) -> dict[str, Any]:
    return operator_page(request.app.state.store, name)


@router.put("/checklist", summary="Сохранить черновик чек-листа новой версией")
async def put_checklist(draft: Checklist, request: Request) -> dict[str, Any]:
    saved = save_checklist(request.app.state.store, draft)
    _log(request, "checklist.save", "checklist", saved["version"], {"pending": len(saved["pending"])})
    return saved


MEDIA = {"json": "application/json", "csv": "text/csv", "md": "text/markdown", "html": "text/html"}


@router.get("/checklist/export", summary="Выгрузить версию чек-листа файлом")
async def get_checklist_export(
    request: Request, v: int | None = None, fmt: Annotated[ExportFormat, Query(alias="format")] = "json"
) -> Response:
    """Файл версии v (без v — текущей); памятка html открывается во вкладке, остальное скачивается."""
    version, body = export_checklist(request.app.state.store, v, fmt)
    _log(request, "export", "checklist", version, {"format": fmt})
    return _file(body, fmt, f"checklist-v{version}")


def _diff_out(result: dict[str, Any] | str) -> Response:
    return JSONResponse(result) if isinstance(result, dict) else Response(result, media_type=MEDIA["md"])


@router.get("/checklist/diff", summary="Разница двух сохранённых версий чек-листа")
async def get_checklist_diff(
    request: Request,
    frm: Annotated[int, Query(alias="from")],
    to: int | None = None,
    fmt: Annotated[DiffFormat, Query(alias="format")] = "json",
) -> Response:
    return _diff_out(diff_versions(request.app.state.store, frm, to, fmt))


@router.post("/checklist/diff", summary="Разница текущей версии и черновика, без сохранения")
async def post_checklist_diff(
    draft: Checklist, request: Request, fmt: Annotated[DiffFormat, Query(alias="format")] = "json"
) -> Response:
    return _diff_out(diff_draft(request.app.state.store, draft, fmt))


@router.put("/owners", summary="Назначить ответственных за причины снижения")
async def put_owners(body: dict[str, Owner], request: Request) -> dict[str, str]:
    owners = save_owners(request.app.state.store, body)
    _log(request, "owners.save", "owners", "", dict(body))
    return owners


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


@router.post("/appeals", summary="Подать апелляцию на ответ по критерию")
async def post_appeal(body: AppealIn, request: Request) -> dict[str, Any]:
    actor = actor_from(request, body.by)
    fields = {**body.model_dump(), "by": signed(actor, body.by)}
    appeal = file_appeal(request.app.state.store, **fields, now=datetime.now(ASTANA))
    _log(request, "appeal.file", "appeal", appeal.id, {"dlg": appeal.dlg, "cid": appeal.cid}, actor)
    return _appeal_out(appeal)


@router.post("/appeals/{appeal_id}/decision", summary="Решение по апелляции")
async def post_decision(appeal_id: str, body: DecisionIn, request: Request) -> dict[str, Any]:
    actor = actor_from(request, body.reviewer)
    fields = {**body.model_dump(), "reviewer": signed(actor, body.reviewer)}
    appeal = decide(request.app.state.store, appeal_id, **fields, now=datetime.now(ASTANA))
    _log(request, "appeal.decide", "appeal", appeal.id, {"status": appeal.status}, actor)
    return _appeal_out(appeal)


@router.post("/decisions", summary="Решение проверяющего без апелляции")
async def post_review(body: ReviewIn, request: Request) -> dict[str, Any]:
    actor = actor_from(request, body.reviewer)
    fields = {**body.model_dump(exclude={"from_"}), "reviewer": signed(actor, body.reviewer)}
    review = record_review(request.app.state.store, frm=body.from_, **fields, now=datetime.now(ASTANA))
    _log(request, "review.decide", "appeal", review.id, {"dlg": body.dlg, "cid": body.cid}, actor)
    return _appeal_out(review)


@router.put("/dialogs/{dialog_id}/answers/{cid}", summary="Ручной ответ по критерию")
async def put_answer(dialog_id: str, cid: str, body: AnswerIn, request: Request) -> dict[str, Any]:
    actor = actor_from(request, body.by)
    by = signed(actor, body.by)
    result = set_answer(request.app.state.store, dlg=dialog_id, cid=cid, a=body.a, reason=body.reason, by=by)
    _log(request, "answer.manual", "dialog", dialog_id, {"cid": cid}, actor)
    return result.model_dump(mode="json", exclude_none=True)


@router.get("/dialogs/{dialog_id}/history")
async def get_history(dialog_id: str, request: Request) -> dict[str, list[dict[str, Any]]]:
    return history(request.app.state.store, dialog_id)


@router.post("/results/{result_id}/restore")
async def post_restore(result_id: int, request: Request) -> dict[str, Any]:
    result = restore(request.app.state.store, result_id)
    _log(request, "result.restore", "result", result_id, {"model": result.model})
    return result.model_dump(mode="json", exclude_none=True)


def _apply(request: Request) -> Apply:
    """Пересобрать оценщик и плашку `mode` без перезапуска; во время запуска — 409."""
    state = request.app.state

    def apply(settings: Settings) -> None:
        _runner(request).use(build_routed(settings, state.prosody, state.store))
        state.settings, state.mode = settings, mode_from_settings(settings)

    return apply


# раздел интерфейса → путь, по которому сервер его умеет; интерфейс показывает раздел только при наличии ключа
FEATURES = {
    "alerts": "/api/alerts",
    "employees": "/api/employees",
    "audit": "/api/audit",
    "reports": "/api/reports",
    "usage": "/api/usage",
    "telemetry": "/api/telemetry",
    "docs": "/docs/",
    "sources": "/api/sources",
    "batches": "/api/batches",
    "routing": "/api/routing",
    "automation": "/api/automation",
}


def _paths(routes: Any) -> set[str]:
    """Пути маршрутов; FastAPI 0.16x оборачивает include_router, пути лежат в `original_router`."""
    out: set[str] = set()
    for r in routes:
        out.add(getattr(r, "path", ""))
        if inner := getattr(r, "original_router", None):
            out |= _paths(inner.routes)
    return out


def features(app: Any) -> list[str]:
    """Ключи разделов, чьи пути есть среди маршрутов приложения."""
    paths = _paths(app.routes)
    return [k for k, p in FEATURES.items() if p in paths or p.rstrip("/") in paths]


@router.get("/config", summary="Режим оценки, без ключей")
async def get_config(request: Request) -> dict[str, Any]:
    return {**view(request.app.state.settings), "features": features(request.app)}


@router.put("/config", summary="Сменить режим оценки без перезапуска")
async def put_config(body: ConfigIn, request: Request) -> dict[str, Any]:
    state = request.app.state
    out = view(configure(state.store, state.settings, body.model_dump(), _apply(request)))
    _log(request, "config.save", "config", "", body.model_dump())  # ключи отбрасывает record
    return out


@router.put("/providers/{provider_id}", summary="Создать или изменить провайдера модели")
async def put_provider_route(provider_id: str, body: ProviderIn, request: Request) -> dict[str, Any]:
    state = request.app.state
    out = view(put_provider(state.store, state.settings, provider_id, body.model_dump(), _apply(request)))
    _log(request, "provider.save", "provider", provider_id, body.model_dump())  # ключ отбрасывает record
    return out


@router.delete("/providers/{provider_id}", summary="Удалить провайдера модели")
async def delete_provider_route(provider_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    out = view(delete_provider(state.store, state.settings, provider_id, _apply(request)))
    _log(request, "provider.delete", "provider", provider_id)
    return out


@router.post("/providers/{provider_id}/check", summary="Проверить связь с провайдером модели")
async def check_provider_route(provider_id: str, request: Request) -> dict[str, Any]:
    return await check_provider(provider(request.app.state.settings, provider_id))


@router.get("/routing")
async def get_routing(request: Request) -> list[dict[str, Any]]:
    return routing_view(request.app.state.settings)


@router.put("/routing")
async def put_routing_route(request: Request, body: Annotated[Any, Body()]) -> list[dict[str, Any]]:
    """Правила обработки целиком, по порядку; тело проверяет сервис, ошибки — 422 по-русски с полем."""
    state = request.app.state
    return routing_view(put_routing(state.store, state.settings, body, _apply(request)))


@router.post("/routing/explain")
async def post_routing_explain(body: ExplainIn, request: Request) -> dict[str, Any]:
    return explain(request.app.state.store, request.app.state.settings, body.dialog_id)


@router.post("/datasets", summary="Загрузить набор по group_id")
async def post_dataset(body: DatasetIn, request: Request) -> dict[str, int]:
    result = await load_group(request.app.state.store, _source(request), body.group_id)
    _log(request, "dataset.load", "dataset", body.group_id, result)
    return result


@router.put("/source", summary="Сохранить ссылку на API набора и загрузить набор")
async def put_source(body: SourceIn, request: Request) -> dict[str, int]:
    """Ссылка API организаторов из интерфейса: сразу загрузка набора, затем автосинхронизация."""
    result = await _syncer(request).configure(body.url, body.group_id)
    _log(request, "dataset.source", "dataset", body.group_id, result)  # ссылку организаторов не пишем
    return result


@router.post("/datasets/upload", summary="Загрузить набор файлом JSON")
async def post_upload(request: Request) -> dict[str, int]:
    """Сырое тело файла: без `UploadFile` и зависимости `python-multipart`."""
    result = load_upload(request.app.state.store, _source(request), await request.body())
    _log(request, "dataset.upload", "dataset", "", result)
    return result


MAX_PROPS = 2048


class TelemetryIn(BaseModel):
    event: Event
    at: AwareDatetime | None = None  # без at — время приёма
    page: Annotated[str, StringConstraints(pattern=TOKEN)]
    props: dict[str, Any] = {}

    @field_validator("props")
    @classmethod
    def _small(cls, props: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(props, ensure_ascii=False).encode()) > MAX_PROPS:
            raise ValueError(f"props больше {MAX_PROPS} байт")
        return props


TELEMETRY = TypeAdapter(Annotated[list[TelemetryIn], Field(max_length=200)])


@router.post("/telemetry", status_code=204, summary="Метрики использования: пакет событий интерфейса")
async def post_telemetry(
    request: Request,
    role: Annotated[str | None, Query(pattern=TOKEN)] = None,
) -> Response:
    """Пакет событий интерфейса. Тело читается как JSON при любом Content-Type: sendBeacon шлёт text/plain.

    Сотрудник — `actor_from` (активный по `X-CQA-User`, его id и роль), без входа — роль из запроса."""
    state = request.app.state
    if state.settings.telemetry == "off":
        return Response(status_code=204)
    if not state.telemetry_limit.take(request.client.host if request.client else "-"):
        return Response(status_code=429)
    try:
        batch = TELEMETRY.validate_json(await request.body())
    except ValidationError as exc:
        raise Invalid(f"Пакет метрик не принят: {exc}") from exc
    now = datetime.now(UTC)
    who = actor_from(request, role or "")
    events = [(e.at or now, e.event, e.page, e.props) for e in batch]
    store_events(state.store, events, who.id or who.name, who.role or role)
    return Response(status_code=204)


@router.get("/usage", summary="Сводка использования системы: json или csv")
async def get_usage(
    request: Request,
    since: date | None = None,
    role: Annotated[str | None, Query(max_length=64)] = None,
    fmt: Annotated[UsageFormat, Query(alias="format")] = "json",
) -> Response:
    """Как сотрудники пользуются системой: json — числа, csv — длинная таблица для Excel."""
    body = usage(request.app.state.store, fmt, since=since, role=role)
    if isinstance(body, dict):
        return JSONResponse(body)
    return Response(
        body, media_type=MEDIA["csv"], headers={"Content-Disposition": 'attachment; filename="usage.csv"'}
    )


@router.post("/runs", summary="Запустить оценку")
async def post_run(body: RunIn, request: Request) -> dict[str, int]:
    state = request.app.state
    runner = _runner(request)
    evaluator, model, override = None, state.mode.model, None
    if body.override is not None:  # оценщик только на этот запуск, сохранённый режим не меняется
        override = body.override.model_dump(exclude_unset=True)
        settings = run_settings(state.settings, override)
        evaluator, model = build_evaluator(settings, state.prosody), mode_from_settings(settings).model
    run_id = runner.start(
        body.dialogs,
        body.criteria,
        force=body.force,
        confirm=body.confirm,
        model=model,
        apply=body.apply,
        override=override,
        evaluator=evaluator,
    )
    picked = None if body.dialogs is None else len(body.dialogs)
    details = {"dialogs": picked, "criteria": body.criteria, "force": body.force, "apply": body.apply}
    recheck = body.force or body.apply == "compare" or override is not None
    _log(request, "run.recheck" if recheck else "run.start", "run", run_id, {**details, "override": override})
    return {"run_id": run_id}


@router.post("/runs/{run_id}/adopt")
async def post_adopt(run_id: int, request: Request, body: AdoptIn | None = None) -> dict[str, int]:
    """Теневые ответы запуска compare — текущими (все или часть по dialogs и criteria)."""
    body = body or AdoptIn()
    result = adopt(request.app.state.store, run_id, body.dialogs, body.criteria)
    _log(request, "run.adopt", "run", run_id, {**body.model_dump(), **result})
    return result


@router.get("/runs")
async def get_runs(request: Request) -> list[dict[str, Any]]:
    return list_runs(request.app.state.store)


@router.get("/runs/compare")  # до /runs/{run_id}: иначе «compare» разбирается как id
async def get_runs_compare(a: int, b: int, request: Request) -> dict[str, Any]:
    return compare_runs(request.app.state.store, a, b)


@router.get("/runs/{run_id}", summary="Прогресс запуска оценки")
async def get_run(run_id: int, request: Request) -> dict[str, Any]:
    return _runner(request).progress(run_id)


@router.post("/runs/{run_id}/cancel", summary="Остановить запуск оценки")
async def cancel_run(run_id: int, request: Request) -> dict[str, str]:
    out = _runner(request).cancel(run_id)
    _log(request, "run.cancel", "run", run_id)
    return out


class EmployeeIn(BaseModel):
    name: str
    role: Role
    team: str = ""
    active: bool = True


@router.get("/employees")
async def get_employees(request: Request) -> list[dict[str, Any]]:
    employees: list[dict[str, Any]] = request.app.state.store.employees()
    return employees


@router.put("/employees/{employee_id}")
async def put_employee_route(employee_id: str, body: EmployeeIn, request: Request) -> dict[str, Any]:
    saved = put_employee(request.app.state.store, employee_id, **body.model_dump())
    _log(request, "employee.save", "employee", employee_id, body.model_dump())
    return saved


@router.post("/employees/import")
async def post_employees_import(request: Request) -> dict[str, int]:
    """Сырое тело CSV `id;name;role;team`, как `/datasets/upload`."""
    result = import_csv(request.app.state.store, await request.body())
    _log(request, "employee.import", "employee", "", result)
    return result


@router.get("/me")
async def get_me(request: Request) -> dict[str, Any]:
    return asdict(actor_from(request))


@router.get("/audit")
async def get_audit(
    request: Request,
    actor: str | None = None,
    action: str | None = None,
    since: str | None = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
    fmt: Annotated[AuditFormat, Query(alias="format")] = "json",
) -> Response:
    """Журнал новыми первыми: json — 500 последних без `limit`, csv — весь отбор и строка `export`."""
    if limit is None and fmt == "json":
        limit = 500
    body = audit_log(request.app.state.store, fmt, actor=actor, action=action, since=since, limit=limit)
    if isinstance(body, list):
        return JSONResponse(body)
    _log(request, "export", "audit", fmt, {"actor": actor, "action": action, "since": since})
    disposition = 'attachment; filename="cqa-audit.csv"'
    return Response(body, media_type=MEDIA[fmt], headers={"Content-Disposition": disposition})


@router.get("/overview")
async def get_overview(request: Request) -> dict[str, Any]:
    return overview(request.app.state.store, datetime.now(ASTANA))
