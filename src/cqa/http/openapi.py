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
    {
        "name": MODE,
        "description": "Режим оценки, провайдеры моделей, проверка связи, сотрудники и журнал действий.",
    },
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
        "`GET /api/runs/{run_id}` и `GET /api/dialogs/{dialog_id}`. `Idempotency-Key` — повтор "
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
        "запускается один запуск; ответ 202 сразу. Конец запуска — опрос `GET /api/runs/{run_id}` "
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
        "Готово и всего пар, цена, вызовы, ETA в секундах, ошибки строками, статус и `dialogs` — статус "
        "диалога (`queued`, `evaluating`, `done`, `error`, `skipped`, `cancelled`) с ходом и ошибкой.",
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
    "PUT /api/dialogs/{dialog_id}/operator": op(
        DIALOGS,
        "Назначить оператора диалогу",
        "Имя оператора до 200 символов; `null` снимает назначение.",
        401,
        404,
        422,
        body={"operator": "Айгерим С."},
        example={"operator": "Айгерим С."},
    ),
    "POST /api/operators/import": op(
        REPORTS,
        "Загрузить операторов из CSV",
        "Сырое тело CSV, как у `/datasets/upload`: файл или текст; назначает операторов диалогам.",
        401,
        422,
    ),
    "GET /api/operators": op(
        REPORTS,
        "Операторы",
        "Список операторов с числом диалогов и средними оценками для коучинга.",
        401,
        503,
    ),
    "GET /api/operators/{name}": op(
        REPORTS, "Страница оператора", "Диалоги, оценки и слабые места одного оператора.", 401, 404, 503
    ),
    "GET /api/overview": op(
        REPORTS,
        "Обзор работы",
        "Сводка работы команды КК: оценено, проверено, апелляции, действия.",
        401,
        503,
    ),
    "GET /api/employees": op(MODE, "Сотрудники", "Список сотрудников с ролью, командой и активностью.", 401),
    "PUT /api/employees/{employee_id}": op(
        MODE,
        "Добавить или изменить сотрудника",
        "Имя, роль, команда, активность; действие пишется в журнал.",
        401,
        422,
        body={"name": "Айгерим С.", "role": "qa", "team": "Чаты", "active": True},
    ),
    "POST /api/employees/import": op(
        MODE,
        "Загрузить сотрудников из CSV",
        "Сырое тело CSV `id;name;role;team`; действие пишется в журнал.",
        401,
        422,
    ),
    "GET /api/me": op(MODE, "Текущий сотрудник", "Кто выполняет запросы: по заголовку `X-CQA-User`.", 401),
    "GET /api/audit": op(
        MODE,
        "Журнал действий",
        "Новые первыми, фильтры `actor`, `action`, `since`; json — 500 последних без `limit`, "
        "csv — весь отбор, выгрузка тоже пишется в журнал.",
        401,
        422,
    ),
    "GET /api/dialogs/{dialog_id}/history": op(
        DIALOGS,
        "История ответов диалога",
        "Все ответы по критериям: запуски, ручные ответы, восстановления.",
        401,
        404,
    ),
    "GET /api/dialogs/{id}/talkstats": op(
        DIALOGS,
        "Статистика разговора",
        "Доли речи, паузы, перебивания с нормами команды; 502 — запись звонка не получена.",
        401,
        404,
        502,
    ),
    "POST /api/results/{result_id}/restore": op(
        EVAL, "Восстановить прежний ответ", "Прежний результат пары снова становится текущим.", 401, 404, 409
    ),
    "GET /api/runs": op(
        EVAL, "Список запусков", "Последние запуски: модель, версия чек-листа, ход, ошибки.", 401
    ),
    "GET /api/runs/compare": op(
        EVAL,
        "Сравнить два запуска",
        "Согласие ответов запусков `a` и `b` по общим парам и расхождения.",
        401,
        404,
        422,
    ),
    "POST /api/runs/{run_id}/adopt": op(
        EVAL,
        "Принять ответы перепроверки",
        "Теневые ответы запуска `compare` становятся текущими: все или часть по `dialogs` и `criteria`.",
        401,
        404,
        409,
        422,
    ),
    "POST /api/batches": op(
        EVAL,
        "Создать пакетное задание",
        "Большой объём частями: батчи по `batch_size` уходят в обычные запуски по приоритету.",
        401,
        404,
        422,
        503,
    ),
    "GET /api/batches": op(
        EVAL, "Пакетные задания", "Задания с ходом, приоритетом и лимитом запросов.", 401, 503
    ),
    "GET /api/batches/{job_id}": op(EVAL, "Пакетное задание", "Ход задания по батчам.", 401, 404, 422, 503),
    "POST /api/batches/{job_id}/{action}": op(
        EVAL,
        "Управлять заданием",
        "Пауза, продолжение, отмена или повтор упавших батчей задания.",
        401,
        404,
        409,
        422,
        503,
    ),
    "GET /api/recommendations": op(
        REPORTS,
        "Рекомендации",
        "Оператору (`id` — имя), проверяющему, руководителю и автору чек-листа; из чисел, без модели.",
        401,
        404,
        422,
    ),
    "GET /api/analytics/{name}": op(
        REPORTS,
        "Расширенная аналитика",
        "Тренд, тепловая карта, драйверы, распределение, срезы, апелляции, качество модели; "
        "в каждом ответе `n`, `low_n` и формулы; фильтры `lang`, `ch`, `operator`, `product`, "
        "`since`, `until`.",
        401,
        422,
        503,
    ),
    "GET /api/reports": op(
        REPORTS, "Каталог отчётов", "Отчёты страницы «Отчёты» со ссылками и форматами.", 401
    ),
    "GET /api/quality": op(
        REPORTS, "Прогоны качества", "Отчёты `make eval` на эталоне: дата, модель, метрики.", 401
    ),
    "GET /api/quality/{report_id}": op(
        REPORTS, "Отчёт о качестве модели", "Один прогон `make eval`: html, json или md.", 401, 404, 422
    ),
    "GET /api/runs/{run_id}/report": op(
        REPORTS, "Отчёт по запуску", "Итоги одного запуска оценки: html, json, csv или md.", 401, 404, 422
    ),
    "GET /api/results/{which}": op(
        REPORTS,
        "Файл результатов набора",
        "`results/dev` или `results/prod`, собранный `make results`.",
        401,
        404,
        422,
    ),
    "GET /api/talkstats/norms": op(
        REPORTS, "Нормы разговора", "Медиана, квартили и границы Тьюки по звонкам с разбором и по чатам.", 401
    ),
    "POST /api/telemetry": op(
        REPORTS,
        "Метрики использования: пакет событий интерфейса",
        "События экранов без данных диалогов; при `CQA_TELEMETRY=off` не сохраняются. Ответ 204.",
        401,
        422,
    ),
    "GET /api/usage": op(
        REPORTS,
        "Сводка использования системы",
        "Сколько и чем пользуются за срок хранения `CQA_TELEMETRY_RETENTION_DAYS`: json или csv.",
        401,
        422,
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
