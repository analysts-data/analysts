"""Интеграционный API для CRM, Dynamics 365 и контакт-центра: оценка без интерфейса (раздел контракта
«Интеграционный API»). Своя схема тел с описаниями полей: они же — подсказки «expected» в ответах 422."""

import hashlib
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

from cqa.domain.models import CriterionResult, Dialog
from cqa.http.api import _runner, _source
from cqa.services.errors import Conflict, Invalid
from cqa.services.integration import dialog_result, finished, run_status, save

router = APIRouter(prefix="/api")

# ponytail: ключи идемпотентности в памяти процесса; таблица в базе, если повторы переживают перезапуск
KEEP_KEYS = 1000


class TurnIn(BaseModel):
    timestamp: str = Field(description='"MM:SS" от начала чата или ISO 8601 для звонка')
    speaker: str = Field(description='"client", "operator", "bot" или "system"')
    text: str = Field(description="текст реплики")


RECORD_EXAMPLE: dict[str, Any] = {
    "conversation_id": "crm-2026-000123",
    "channel": "agent chat",
    "language": "ru",
    "operator": "Айгерим С.",
    "transcript": [
        {"timestamp": "00:00", "speaker": "client", "text": "Здравствуйте, не проходит пополнение счёта."},
        {"timestamp": "00:20", "speaker": "operator", "text": "Здравствуйте! Меня зовут Айгерим, проверю."},
        {"timestamp": "01:40", "speaker": "operator", "text": "Платёж зачислен, обновите приложение."},
        {"timestamp": "02:00", "speaker": "client", "text": "Вижу, спасибо."},
    ],
}
PASTE_EXAMPLE: dict[str, Any] = {
    "title": "Жалоба на комиссию",
    "ch": "chat",
    "text": "Клиент: Почему списали комиссию?\nОператор: Здравствуйте! Проверю операцию.",
}


class RecordIn(BaseModel):
    """Запись в формате организаторов; лишние поля (оператор, метки CRM) сохраняются как есть."""

    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [RECORD_EXAMPLE]})
    conversation_id: str = Field(
        min_length=1, description="id диалога в вашей системе; повтор id не оценивается заново"
    )
    channel: str = Field(description='"agent chat" или "voice call"')
    language: str = Field(description='"ru", "kz" или "en"')
    transcript: list[TurnIn] = Field(
        min_length=1, description="реплики по порядку: [{timestamp, speaker, text}]"
    )
    audio_url: str | None = Field(None, description="ссылка на запись звонка; в ответы не попадает")
    operator: str | None = Field(None, description="имя или id оператора")


class TextIn(BaseModel):
    """Диалог текстом, как вставка в интерфейсе: строки «Роль: текст»."""

    model_config = ConfigDict(json_schema_extra={"examples": [PASTE_EXAMPLE]})
    title: str = Field("", description="название диалога; пусто — как у загруженных")
    ch: Literal["chat", "call"] = Field(description='"chat" или "call"')
    text: str = Field(description="строки «Клиент: …», «Оператор: …», «Бот: …», «Система: …»")


def _format(v: Any) -> str | None:
    if isinstance(v, dict):
        return "record" if "conversation_id" in v else "paste" if "text" in v else None
    return "record" if isinstance(v, RecordIn) else "paste" if isinstance(v, TextIn) else None


FORMATS = ("record", "paste")  # метки вариантов: validation.py убирает их из пути поля
Item = Annotated[
    Annotated[RecordIn, Tag("record")] | Annotated[TextIn, Tag("paste")],
    Discriminator(
        _format,
        custom_error_type="dialog_format",
        custom_error_message="тело не похоже ни на запись организаторов, ни на текст диалога",
    ),
]


class BatchIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"dialogs": [RECORD_EXAMPLE, PASTE_EXAMPLE]}]})
    dialogs: list[Item] = Field(
        min_length=1, max_length=100, description="от 1 до 100 диалогов в любом из двух форматов"
    )


class CriterionOut(CriterionResult):
    cid: str = Field(description="id критерия текущего чек-листа")
    name: str = Field(description="название критерия")


class DialogResult(BaseModel):
    dialog_id: str
    total: float | None = Field(
        description="итог 0–100 с учётом решений по апелляциям; null — нет применимых ответов"
    )
    critical_flag: bool = Field(description="есть грубая ошибка (флаг)")
    criteria: list[CriterionOut] = Field(description="ответы по критериям: ответ, основание, реплики, цитата")
    results_v1: dict[str, Any] | None = Field(
        description="запись JSON 1.0 организаторов по диалогу; null — карта кодов не подходит к чек-листу"
    )


class EvaluateOut(DialogResult):
    run_id: int
    errors: list[str] = Field(
        description="ошибки запуска по этому диалогу: модель недоступна, реальный звонок без разрешения"
    )


class DialogOut(DialogResult):
    dialog: Dialog = Field(description="диалог по контракту: реплики, свёртки, текущие `res`")


class AcceptedOut(BaseModel):
    dialog_id: str
    run_id: int


class BatchOut(BaseModel):
    run_id: int
    dialog_ids: list[str]


class DialogStatus(BaseModel):
    dialog_id: str
    status: Literal["queued", "evaluating", "done", "error", "cancelled"]
    done: int = Field(description="критериев с ответом текущего чек-листа")
    total: int = Field(description="критериев в чек-листе")
    error: str | None


class RunStatusOut(BaseModel):
    run_id: int
    status: Literal["running", "done", "cancelled"]
    done: int
    total: int
    cost: float
    calls: int
    eta_s: int | None
    errors: list[str]
    dialogs: list[DialogStatus]


IdempotencyKey = Annotated[
    str | None,
    Header(
        max_length=255,
        description="повтор запроса с тем же ключом и телом вернёт тот же ответ без новой оценки",
    ),
]
Made = tuple[int, dict[str, Any]]


async def _idempotent(
    request: Request, key: str | None, body: BaseModel, make: Callable[[], Awaitable[Made]]
) -> JSONResponse:
    """Ответ 2xx запоминается по ключу; тот же ключ с другим телом — 422, пока первый идёт — 409."""
    if key is None:
        code, content = await make()
        return JSONResponse(content, code)
    memo: dict[str, tuple[str, int, dict[str, Any]]] = request.app.state.idempotency
    pending: set[str] = request.app.state.idempotency_pending
    digest = hashlib.sha256(f"{request.url.path}\n{body.model_dump_json()}".encode()).hexdigest()
    if key in memo:
        seen, code, content = memo[key]
        if seen != digest:
            raise Invalid(f"Idempotency-Key {key} уже использован с другим телом запроса")
        return JSONResponse(content, code)
    if key in pending:
        raise Conflict(f"Запрос с Idempotency-Key {key} ещё выполняется: повторите позже")
    pending.add(key)
    try:
        code, content = await make()
    finally:
        pending.discard(key)
    memo[key] = (digest, code, content)
    while len(memo) > KEEP_KEYS:
        memo.pop(next(iter(memo)))
    return JSONResponse(content, code)


@router.post("/evaluate", response_model=EvaluateOut)
async def post_evaluate(
    body: Item, request: Request, wait: bool = True, idempotency_key: IdempotencyKey = None
) -> JSONResponse:
    async def make() -> Made:
        runner, store = _runner(request), request.app.state.store
        runner.ensure_idle()  # до сохранения: при 409 диалог не появляется
        [dialog_id] = save(store, _source(request), [body.model_dump()])
        run_id = runner.start([dialog_id], None)
        if not wait or not await finished(runner, run_id):
            return 202, {"dialog_id": dialog_id, "run_id": run_id}
        result = dialog_result(store, dialog_id)
        del result["dialog"]
        return 200, {**result, "run_id": run_id, "errors": runner.progress(run_id)["errors"]}

    return await _idempotent(request, idempotency_key, body, make)


@router.post("/evaluate/batch", status_code=202, response_model=BatchOut)
async def post_batch(body: BatchIn, request: Request, idempotency_key: IdempotencyKey = None) -> JSONResponse:
    async def make() -> Made:
        runner = _runner(request)
        runner.ensure_idle()
        ids = save(request.app.state.store, _source(request), [d.model_dump() for d in body.dialogs])
        return 202, {"run_id": runner.start(ids, None), "dialog_ids": ids}

    return await _idempotent(request, idempotency_key, body, make)


@router.get("/dialogs/{dialog_id}", response_model=DialogOut)
async def get_dialog(dialog_id: str, request: Request) -> JSONResponse:
    return JSONResponse(
        dialog_result(request.app.state.store, dialog_id)
    )  # диалог без пустых полей, как в /state


@router.get("/runs/{run_id}/dialogs", response_model=RunStatusOut)
async def get_run_dialogs(run_id: int, request: Request) -> dict[str, Any]:
    return run_status(request.app.state.store, _runner(request), run_id)
