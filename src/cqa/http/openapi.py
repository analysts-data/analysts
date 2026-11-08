"""Схема OpenAPI `/api/openapi.json` по-русски: разделы, описания, коды ошибок с примерами, примеры тел.

Описания путей — одна таблица `DOCS` поверх схемы FastAPI (`app.openapi`), а не в декораторах:
тест требует строку для каждого пути, снимок `docs/openapi.json` обновляет `make openapi`.
"""

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

SETS, DIALOGS, EVAL, APPEALS, CHECKLIST, REPORTS, MODE, INTEGRATION = (
    "Наборы",
    "Диалоги",
    "Оценка",
    "Апелляции",
    "Чек-лист",
    "Отчёты",
    "Режим и модели",
    "Интеграция",
)
TAGS = [
    {"name": INTEGRATION, "description": "Оценка без интерфейса для CRM, Dynamics 365 и контакт-центра."},
    {"name": SETS, "description": "Загрузка наборов организаторов: по group_id, файлом, автосинхронизация."},
    {
        "name": DIALOGS,
        "description": "Состояние интерфейса, вставка текста, отметка «проверено», запись звонка.",
    },
    {"name": EVAL, "description": "Запуски оценки моделью и ручной ответ по критерию."},
    {"name": APPEALS, "description": "Апелляции операторов и решения специалиста КК."},
    {"name": CHECKLIST, "description": "Версии чек-листа: сохранение, экспорт, разница версий."},
    {"name": REPORTS, "description": "Отчёт для руководства, оценки для Excel, владельцы причин."},
    {"name": MODE, "description": "Режим оценки, провайдеры моделей, проверка связи."},
]
DESCRIPTION = """API сервиса контроля качества диалогов (CQA): интерфейс и внешние системы ходят в одни пути.

Ошибки — JSON `{"detail": "<текст по-русски>"}`; у 422 по телу — ещё `errors: [{path, message, expected}]`,
у 409 из-за активного запуска — `run_id`, `done`, `total`, `eta_s`. Коды: 401 — нужен токен
(только если задан `CQA_ACCESS_TOKEN`), 404 — нет диалога, критерия, апелляции или запуска,
409 — идёт другой запуск или конфликт решения, 422 — тело или параметры не прошли проверку,
502 — API организаторов или запись звонка недоступны, 503 — источник или оценщик не подключён.

Доступ: при `CQA_ACCESS_TOKEN` — заголовок `Authorization: Bearer <токен>` или cookie `cqa_access`.
Примеры curl и Python — `docs/api-examples.md`."""

DETAIL = {"type": "object", "properties": {"detail": {"type": "string"}}, "required": ["detail"]}
FIELD = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "message": {"type": "string"}, "expected": {"type": "string"}},
}
VALIDATION = {
    "type": "object",
    "properties": {"detail": {"type": "string"}, "errors": {"type": "array", "items": FIELD}},
    "required": ["detail"],
}
CONFLICT = {
    "type": "object",
    "properties": {
        "detail": {"type": "string"},
        "run_id": {"type": "integer"},
        "done": {"type": "integer"},
        "total": {"type": "integer"},
        "eta_s": {"type": ["integer", "null"]},
    },
    "required": ["detail"],
}


def _error(description: str, schema: dict[str, Any], **examples: dict[str, Any]) -> dict[str, Any]:
    content = {"schema": schema, "examples": {k: {"value": v} for k, v in examples.items()}}
    return {"description": description, "content": {"application/json": content}}


ERRORS: dict[int, dict[str, Any]] = {
    401: _error(
        "Нужен токен: `Authorization: Bearer <токен>` или cookie `cqa_access` (только при CQA_ACCESS_TOKEN)",
        DETAIL,
        token={"detail": "Нужен вход по ссылке с токеном"},
    ),
    404: _error(
        "Не найден диалог, критерий, апелляция, запуск или версия",
        DETAIL,
        dialog={"detail": "Диалог crm-2026-000123 не найден"},
        run={"detail": "Запуск 42 не найден"},
    ),
    409: _error(
        "Конфликт: идёт другой запуск (номер, ход и ETA в теле), повтор Idempotency-Key ещё выполняется, "
        "решение по паре уже есть",
        CONFLICT,
        run={"detail": "Запуск 41 ещё идёт", "run_id": 41, "done": 24, "total": 80, "eta_s": 95},
        idempotency={"detail": "Запрос с Idempotency-Key crm-42 ещё выполняется: повторите позже"},
    ),
    422: _error(
        "Тело или параметры не прошли проверку: путь поля, сообщение и ожидаемый формат",
        VALIDATION,
        field={
            "detail": "Запрос не прошёл проверку: language — обязательное поле",
            "errors": [
                {"path": "language", "message": "обязательное поле", "expected": '"ru", "kz" или "en"'}
            ],
        },
        rule={"detail": "Idempotency-Key crm-42 уже использован с другим телом запроса"},
    ),
    502: _error(
        "API организаторов не ответил или запись звонка не получена",
        DETAIL,
        upstream={"detail": "набор DEV: API организаторов ответил 500"},
    ),
    503: _error(
        "Источник наборов или оценщик не подключён",
        DETAIL,
        unavailable={"detail": "Оценка моделью не подключена"},
    ),
}

RECORD = {
    "conversation_id": "crm-2026-000123",
    "channel": "agent chat",
    "language": "ru",
    "transcript": [
        {"timestamp": "00:00", "speaker": "client", "text": "Здравствуйте, не проходит пополнение."},
        {"timestamp": "00:20", "speaker": "operator", "text": "Здравствуйте! Проверю платёж."},
    ],
}
APPEAL = {
    "id": "ap-1",
    "kind": "appeal",
    "dlg": "crm-2026-000123",
    "cid": "<id критерия>",
    "from": "no",
    "ask": "yes",
    "ev": [4],
    "by": "Оператор",
    "at": "08.11 10:05",
    "status": "pending",
    "comment": "Срок ответа назван в реплике 4",
}


def op(
    tag: str,
    summary: str,
    description: str,
    *codes: int,
    body: Any = None,
    example: Any = None,
    media: str = "application/json",
) -> dict[str, Any]:
    return {
        "tag": tag,
        "summary": summary,
        "description": description,
        "codes": codes,
        "body": body,
        "example": example,
        "media": media,
    }


DOCS: dict[str, dict[str, Any]] = {
    "GET /api/health": op(
        INTEGRATION, "Сервер жив", "Открыт без токена: для мониторинга.", example={"ok": True}
    ),
    "POST /api/evaluate": op(
        INTEGRATION,
        "Оценить один диалог",
        "Тело — запись организаторов (`conversation_id`, `channel`, `language`, `transcript`, необязательные "
        "`audio_url`, `operator`) или текст как во вставке (`text`, `ch`, `title`). Диалог сохраняется "
        "(повтор `conversation_id` не заменяет и не оценивает заново), оценивается текущим чек-листом тем же "
        "запуском, что «Оценить» в интерфейсе: реальный звонок уходит модели только с CQA_ALLOW_REAL_DATA=1, "
        "текст обезличивается. `wait=true` (по умолчанию) — ответ 200 с итогом, ответами и записью JSON 1.0; "
        "если оценка дольше 120 с или `wait=false` — 202 `{dialog_id, run_id}`, дальше опрос "
        "`GET /api/runs/{run_id}/dialogs` и `GET /api/dialogs/{dialog_id}`. `Idempotency-Key` — повтор "
        "с тем же ключом и телом вернёт тот же ответ без новой оценки.",
        401,
        409,
        422,
        503,
        example={
            "dialog_id": "crm-2026-000123",
            "run_id": 41,
            "total": 87.5,
            "critical_flag": False,
            "criteria": [
                {
                    "cid": "<id критерия>",
                    "name": "<название>",
                    "a": "yes",
                    "ev": [2],
                    "why": "…",
                    "quote": "…",
                }
            ],
            "results_v1": {
                "conversation_id": "crm-2026-000123",
                "status": "ok",
                "criteria": [],
                "score": {"final_score": 87.5, "critical_flag": False},
            },
            "errors": [],
        },
    ),
    "POST /api/evaluate/batch": op(
        INTEGRATION,
        "Оценить пакет до 100 диалогов",
        "Каждый элемент — в любом из двух форматов `POST /api/evaluate`. Все диалоги сохраняются, "
        "запускается один запуск; ответ 202 сразу. Конец запуска — опрос `GET /api/runs/{run_id}/dialogs` "
        "или вебхук `run.finished` на CQA_WEBHOOK_URL (подпись `X-CQA-Signature: sha256=<HMAC тела>`, "
        "без текста диалогов). `Idempotency-Key` — как у одного диалога.",
        401,
        409,
        422,
        503,
        example={"run_id": 42, "dialog_ids": ["crm-2026-000123", "paste-7"]},
    ),
    "GET /api/dialogs/{dialog_id}": op(
        INTEGRATION,
        "Диалог с оценкой",
        "Диалог по контракту с текущими `res`, итог и грубая ошибка с учётом решений по апелляциям, "
        "ответы по критериям и запись JSON 1.0 организаторов.",
        401,
        404,
    ),
    "GET /api/runs/{run_id}/dialogs": op(
        INTEGRATION,
        "Ход запуска по каждому диалогу",
        "Ход запуска как `GET /api/runs/{run_id}` и статус каждого диалога: `queued`, `evaluating`, `done`, "
        "`error` (с текстом ошибки), `cancelled`; `done`/`total` — критерии с ответом из всех. Состав "
        "запуска помнит процесс сервера: после перезапуска `dialogs` пуст.",
        401,
        404,
        503,
    ),
    "GET /api/results": op(
        INTEGRATION,
        "Результаты в формате JSON 1.0",
        'Файл результатов организаторов (`schema_version: "1.0"`) по `ids` в их порядке, без `ids` — по всем '
        "диалогам. Ответы с учётом решений по апелляциям; не оценённый или неизвестный диалог — запись "
        '`status: "error"` с причиной. `model.name` — модель текущего режима.',
        401,
        409,
        422,
        503,
        example={
            "schema_version": "1.0",
            "team_name": "analysts",
            "model": {"mode": "external_api", "name": "qwen3-6"},
            "results": [
                {
                    "conversation_id": "crm-2026-000123",
                    "status": "ok",
                    "criteria": [
                        {"criterion_id": "<код>", "value": True, "rationale": "…", "evidence_turns": [2]}
                    ],
                    "score": {"final_score": 87.5, "critical_flag": False},
                }
            ],
        },
    ),
    "GET /api/state": op(
        DIALOGS,
        "Всё состояние интерфейса",
        "Чек-лист, версии, диалоги с текущими ответами, апелляции, владельцы причин, режим данных, "
        "источник набора. Для внешних систем удобнее `GET /api/dialogs/{dialog_id}`.",
        401,
        503,
    ),
    "POST /api/dialogs/text": op(
        DIALOGS,
        "Сохранить диалог из текста",
        "Строки «Роль: текст» (клиент, оператор, бот, система); строка без роли продолжает реплику. "
        "`id` — `paste-<n>`, язык по тексту. Оценка не запускается: для оценки сразу — `POST /api/evaluate`.",
        401,
        422,
        body={
            "title": "Жалоба",
            "ch": "chat",
            "text": "Клиент: Почему списали комиссию?\nОператор: Проверю.",
        },
        example={"id": "paste-7"},
    ),
    "POST /api/dialogs/{dialog_id}/reviewed": op(
        DIALOGS,
        "Отметить диалог проверенным",
        "Снятие отметки возвращает диалог в верхние группы очереди.",
        401,
        404,
        422,
        body={"reviewed": True},
        example={"ok": True},
    ),
    "GET /api/dialogs/{id}/audio": op(
        DIALOGS,
        "Запись звонка",
        "302 на свежую подписанную ссылку MP3; сами ссылки организаторов в ответы не попадают.",
        401,
        404,
        502,
    ),
    "GET /api/dialogs/{id}/player": op(
        DIALOGS,
        "Плеер организаторов",
        "302 на плеер организаторов: запасной путь для реплик без `s`.",
        401,
        404,
    ),
    "GET /api/dialogs/{id}/prosody": op(
        DIALOGS,
        "Интонация звонка",
        "Темп, паузы, перебивания и громкость по звуку записи; считается локально и кэшируется.",
        401,
        404,
        502,
    ),
    "POST /api/datasets": op(
        SETS,
        "Получить набор организаторов",
        "Набор по `group_id`: новые диалоги добавляются, дубли по `id` и битые записи — в `skipped`.",
        401,
        422,
        502,
        503,
        body={"group_id": "DEV"},
        example={"added": 65, "skipped": 0},
    ),
    "POST /api/datasets/upload": op(
        SETS,
        "Загрузить набор файлом",
        "Сырое тело — JSON в формате API организаторов (`{isSuccess, data: {records}}`).",
        401,
        422,
        503,
        example={"added": 10, "skipped": 1},
    ),
    "PUT /api/source": op(
        SETS,
        "Ссылка API организаторов",
        "Набор загружается сразу; ссылка сохраняется после удачной загрузки и включает автосинхронизацию "
        "раз в 5 минут. Нужен `https://`; ссылка не уходит ни в один ответ.",
        401,
        422,
        502,
        503,
        body={"url": "https://<адрес организаторов>", "group_id": "DEV"},
        example={"added": 65, "skipped": 0},
    ),
    "POST /api/runs": op(
        EVAL,
        "Запустить оценку",
        "Пары диалог × критерий без ответа текущего чек-листа, в порядке `dialogs`; `null` — все. "
        "Один запуск за раз: второй — 409 с номером, ходом и ETA активного.",
        401,
        404,
        409,
        422,
        503,
        body={"dialogs": ["crm-2026-000123"], "criteria": None},
        example={"run_id": 42},
    ),
    "GET /api/runs/{run_id}": op(
        EVAL,
        "Ход запуска",
        "Готово и всего пар, цена, вызовы, ETA в секундах, ошибки строками, статус.",
        401,
        404,
        422,
        503,
        example={
            "done": 8,
            "total": 16,
            "cost": 0.012,
            "calls": 8,
            "eta_s": 30,
            "errors": [],
            "status": "running",
        },
    ),
    "POST /api/runs/{run_id}/cancel": op(
        EVAL,
        "Отменить запуск",
        "Диалоги в работе завершаются и сохраняются, новые не начинаются; повторный запуск продолжает.",
        401,
        404,
        409,
        422,
        503,
        example={"status": "cancelled"},
    ),
    "PUT /api/dialogs/{dialog_id}/answers/{cid}": op(
        EVAL,
        "Ручной ответ по критерию",
        'Новый результат пары с `model: "вручную"`; ответ модели остаётся в базе. Открытая апелляция или '
        "решение по паре — 409.",
        401,
        404,
        409,
        422,
        body={"a": "yes", "reason": "Срок назван в реплике 4", "by": "Специалист КК"},
    ),
    "POST /api/appeals": op(
        APPEALS,
        "Подать апелляцию",
        "Оператор оспаривает ответ по критерию: `ask` — ответ, который он считает верным, `ev` — реплики.",
        401,
        404,
        409,
        422,
        body={
            "dlg": "crm-2026-000123",
            "cid": "<id критерия>",
            "ask": "yes",
            "ev": [4],
            "comment": "…",
            "by": "Оператор",
        },
        example=APPEAL,
    ),
    "POST /api/appeals/{appeal_id}/decision": op(
        APPEALS,
        "Решить апелляцию",
        "Специалист КК оставляет ответ или меняет на `to`; причина обязательна. Итог считается с решением.",
        401,
        404,
        409,
        422,
        body={"to": "yes", "reason": "Срок назван", "reviewer": "Специалист КК"},
    ),
    "POST /api/decisions": op(
        APPEALS,
        "Решение без апелляции",
        'Решение по расхождению моделей или проваленному основанию: Appeal с `kind: "review"`.',
        401,
        404,
        409,
        422,
        body={
            "dlg": "crm-2026-000123",
            "cid": "<id критерия>",
            "from": "no",
            "to": "yes",
            "reason": "…",
            "reviewer": "Специалист КК",
        },
    ),
    "PUT /api/checklist": op(
        CHECKLIST,
        "Сохранить новую версию чек-листа",
        "Черновик Checklist — новая версия; критерии с изменённым смыслом ждут переоценки (`pending`).",
        401,
        409,
        422,
        example={"version": 4, "pending": ["<id критерия>"]},
    ),
    "GET /api/checklist/export": op(
        CHECKLIST,
        "Экспорт версии чек-листа",
        "Файл версии `v` (без `v` — текущей): json, csv, md или html-памятка для печати.",
        401,
        404,
        422,
        media="text/plain",
    ),
    "GET /api/checklist/diff": op(
        CHECKLIST,
        "Разница версий",
        "Разница версий `from` → `to` (без `to` — текущая): json или md.",
        401,
        404,
        422,
    ),
    "POST /api/checklist/diff": op(
        CHECKLIST, "Разница с черновиком", "Текущая версия → черновик из тела; ничего не сохраняет.", 401, 422
    ),
    "GET /api/report": op(
        REPORTS,
        "Отчёт для руководства",
        "html — страница A4 для печати, json — числа для аналитики, md — для вики и почты; "
        "фильтры `lang` и `ch` необязательны.",
        401,
        422,
        503,
    ),
    "GET /api/scores/export": op(
        REPORTS,
        "Оценки для Excel",
        "CSV: `wide` — строка на диалог, `long` — строка на пару диалог × критерий; фильтры `lang` и `ch`.",
        401,
        422,
        503,
    ),
    "PUT /api/owners": op(
        REPORTS,
        "Владельцы причин",
        "Кому чинить причину сниженного ответа: Инструкция, Сервис или Продукт; ответ — весь словарь.",
        401,
        422,
        body={"Не назван срок ответа": "Инструкция"},
        example={"Не назван срок ответа": "Инструкция"},
    ),
    "GET /api/config": op(
        MODE,
        "Режим оценки",
        "Провайдер, модель, второе мнение, обезличивание, разрешение реальных данных; без ключей.",
        401,
    ),
    "PUT /api/config": op(
        MODE,
        "Сменить режим оценки",
        "Применяется без перезапуска; во время запуска — 409; ошибка конфигурации — 422, режим не меняется.",
        401,
        409,
        422,
        body={
            "llm_provider": "env",
            "anonymize": True,
            "verifier": None,
            "evaluator": "llm",
            "allow_real_data": False,
        },
    ),
    "PUT /api/providers/{provider_id}": op(
        MODE,
        "Добавить или изменить провайдера",
        "Модель OpenAI-совместимая, свой ключ; пустой `key` оставляет сохранённый; во время запуска — 409.",
        401,
        409,
        422,
        body={
            "label": "Qwen в РК",
            "base_url": "https://llm.example.kz/v1",
            "model": "qwen3-6",
            "where": "kz",
            "key": "",
        },
    ),
    "DELETE /api/providers/{provider_id}": op(
        MODE,
        "Удалить провайдера",
        "Активного провайдера удалить нельзя; во время запуска — 409.",
        401,
        404,
        409,
        422,
    ),
    "POST /api/providers/{provider_id}/check": op(
        MODE,
        "Проверить связь с провайдером",
        "Синтетический запрос мимо записей: реальные данные не уходят.",
        401,
        404,
        example={"ok": True, "ms": 640},
    ),
}


def _apply(operation: dict[str, Any], doc: dict[str, Any]) -> None:
    operation["tags"] = [doc["tag"]]
    operation["summary"] = doc["summary"]
    operation["description"] = doc["description"]
    responses = operation["responses"]
    if "422" in responses:  # проверка тела FastAPI отвечает в форме validation.py
        responses["422"] = ERRORS[422]
    for code in doc["codes"]:
        responses[str(code)] = ERRORS[code]
    if doc["body"] is not None:
        content = operation.setdefault("requestBody", {}).setdefault("content", {})
        content.setdefault(doc["media"], {})["example"] = doc["body"]
    if doc["example"] is not None:
        ok = next(c for c in ("200", "202") if c in responses)
        responses[ok].setdefault("content", {}).setdefault("application/json", {})["example"] = doc["example"]


def document(app: FastAPI) -> None:
    """`app.openapi` с разделами и таблицей `DOCS`; путь без строки остаётся как есть (тест ловит)."""

    def schema() -> dict[str, Any]:
        if app.openapi_schema is None:
            spec = get_openapi(
                title=app.title, version=app.version, description=DESCRIPTION, routes=app.routes, tags=TAGS
            )
            for path, operations in spec["paths"].items():
                for method, operation in operations.items():
                    if doc := DOCS.get(f"{method.upper()} {path}"):
                        _apply(operation, doc)
            if "HTTPValidationError" not in json.dumps(spec["paths"]):
                for name in ("HTTPValidationError", "ValidationError"):
                    spec["components"]["schemas"].pop(name, None)
            spec["components"]["securitySchemes"] = {
                "bearer": {"type": "http", "scheme": "bearer", "description": "CQA_ACCESS_TOKEN"},
                "cookie": {"type": "apiKey", "in": "cookie", "name": "cqa_access"},
            }
            spec["security"] = [{"bearer": []}, {"cookie": []}, {}]  # {} — сервер без токена
            app.openapi_schema = spec
        return app.openapi_schema

    app.openapi = schema  # type: ignore[method-assign]


def snapshot() -> str:
    from cqa.http.app import create_app  # app импортирует этот модуль
    from cqa.settings import Settings

    spec = create_app(Settings(db_path=":memory:")).openapi()  # схема от .env не зависит
    return json.dumps(spec, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":  # make openapi
    Path(sys.argv[1]).write_text(snapshot(), encoding="utf-8")
