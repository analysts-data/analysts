# Интеграционный API: примеры

Как CRM, Dynamics 365 или платформа контакт-центра оценивает диалоги без интерфейса. Полная схема с примерами и кодами ошибок: `GET /api/openapi.json` (снимок в [`openapi.json`](openapi.json), страница — `/docs/api`). Договорённости описаны в `design/contract.md`, раздел «Интеграционный API».

Во всех примерах сервер работает на `http://127.0.0.1:8020`. Если задан `CQA_ACCESS_TOKEN`, добавьте заголовок `Authorization: Bearer <токен>`. Без токена сервер открыт.

```bash
export CQA=http://127.0.0.1:8020
export AUTH="Authorization: Bearer $CQA_ACCESS_TOKEN"   # только если токен задан
```

```python
import httpx

cqa = httpx.Client(base_url="http://127.0.0.1:8020", timeout=150,
                   headers={"Authorization": "Bearer <токен>"})  # без токена — headers не нужен
```

## 1. Один диалог, ответ сразу

Тело принимается в одном из двух форматов: запись в формате организаторов или текст строками «Роль: текст», как во вставке. Сервер сохраняет диалог и оценивает его текущим чек-листом. Ответ приходит, когда оценка готова; ждать приходится до 120 секунд.

```bash
curl -sS -X POST "$CQA/api/evaluate" -H "$AUTH" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: crm-2026-000123' \
  -d '{"conversation_id": "crm-2026-000123", "channel": "agent chat", "language": "ru",
       "operator": "Айгерим С.",
       "transcript": [
         {"timestamp": "00:00", "speaker": "client",   "text": "Здравствуйте, не проходит пополнение."},
         {"timestamp": "00:20", "speaker": "operator", "text": "Здравствуйте! Меня зовут Айгерим, проверю."},
         {"timestamp": "01:40", "speaker": "operator", "text": "Платёж зачислен, обновите приложение."}]}'
```

```python
r = cqa.post("/api/evaluate", json={"title": "Жалоба на комиссию", "ch": "chat",
             "text": "Клиент: Почему списали комиссию?\nОператор: Здравствуйте! Проверю операцию."},
             headers={"Idempotency-Key": "ticket-5512"})
r.raise_for_status()
if r.status_code == 200:
    res = r.json()
    print(res["dialog_id"], res["total"], res["critical_flag"])
    for c in res["criteria"]:
        print(c["cid"], c["name"], c["a"], c["why"])
    record = res["results_v1"]          # запись файла JSON 1.0 организаторов
else:                                    # 202: оценка дольше 120 с, дальше опрос (раздел 2)
    run_id = r.json()["run_id"]
```

Ответ 200 выглядит так: `{dialog_id, run_id, total, critical_flag, criteria: [{cid, name, a, ev, why, quote, …}], results_v1, errors}`. Если в `errors` есть строки, модель не оценила диалог. Например, реальный звонок уходит модели только с `CQA_ALLOW_REAL_DATA=1`. Повтор с тем же `conversation_id` диалог не заменяет и заново не оценивает. Повтор с тем же `Idempotency-Key` и тем же телом возвращает сохранённый ответ.

## 2. Без ожидания: 202 и опрос

```bash
curl -sS -X POST "$CQA/api/evaluate?wait=false" -H "$AUTH" -H 'Content-Type: application/json' \
  -d @dialog.json                                   # → 202 {"dialog_id": "...", "run_id": 42}
curl -sS "$CQA/api/runs/42/dialogs" -H "$AUTH"      # статус каждого диалога
curl -sS "$CQA/api/dialogs/crm-2026-000123" -H "$AUTH"
```

```python
import time

acc = cqa.post("/api/evaluate", params={"wait": "false"}, json=dialog).json()
while (st := cqa.get(f"/api/runs/{acc['run_id']}/dialogs").json())["status"] == "running":
    print(st["done"], "/", st["total"], "ETA", st["eta_s"], [d["status"] for d in st["dialogs"]])
    time.sleep(2)
result = cqa.get(f"/api/dialogs/{acc['dialog_id']}").json()   # итог, ответы, results_v1, dialog
```

Статус диалога принимает значения `queued`, `evaluating`, `done`, `error` (текст ошибки в поле `error`) и `cancelled`.

## 3. Пакет и вебхук

Задайте на сервере `CQA_WEBHOOK_URL=https://crm.example/hooks/cqa` и, по желанию, `CQA_WEBHOOK_SECRET`. Пакет принимает от 1 до 100 диалогов в любом из двух форматов. Ответ 202 приходит сразу.

```bash
curl -sS -X POST "$CQA/api/evaluate/batch" -H "$AUTH" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: nightly-2026-11-08' \
  -d '{"dialogs": [ {...запись...}, {"title": "Звонок 7", "ch": "call", "text": "Клиент: …\nОператор: …"} ]}'
# → 202 {"run_id": 43, "dialog_ids": ["crm-2026-000123", "paste-8"]}
```

Когда запуск закончится, сервер отправит `POST` на `CQA_WEBHOOK_URL`. Текста диалогов в событии нет:

```json
{"event": "run.finished", "run_id": 43, "status": "done", "done": 16, "total": 16,
 "errors": [], "dialog_ids": ["crm-2026-000123", "paste-8"]}
```

Приёмник проверяет подпись `X-CQA-Signature: sha256=<hex>`. Это HMAC-SHA256 сырого тела на ключе `CQA_WEBHOOK_SECRET`:

```python
import hashlib, hmac

def verify(body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

Если доставка не удалась, сервер пишет строку в журнал и не повторяет отправку. На такой случай есть опрос `GET /api/runs/{run_id}/dialogs`.

## 4. Результаты в формате JSON 1.0

Файл результатов организаторов строится по выбранным диалогам, без `ids` — по всем. Ответы учитывают решения по апелляциям. Если диалог не оценён, в файле остаётся запись `status: "error"` с причиной.

```bash
curl -sS "$CQA/api/results?ids=crm-2026-000123&ids=paste-8" -H "$AUTH" -o results.json
```

```python
doc = cqa.get("/api/results", params=[("ids", i) for i in batch["dialog_ids"]]).json()
assert doc["schema_version"] == "1.0"
```

Оценки для Excel выгружаются отдельно: `GET /api/scores/export?shape=wide|long` (CSV).

## 5. Отчёты

```bash
curl -sS "$CQA/api/report?format=json&lang=RU&ch=call" -H "$AUTH"   # числа для аналитики
curl -sS "$CQA/api/report?format=md" -H "$AUTH" -o report.md         # для вики и почты
curl -sS "$CQA/api/report" -H "$AUTH" -o report.html                 # A4 для печати
```

```python
summary = cqa.get("/api/report", params={"format": "json"}).json()["summary"]
print(summary["avg_total"], summary["risk"]["share"], summary["needs_review"])
```

## Ошибки

Тело ошибки — JSON со строкой `detail` по-русски. Все коды с примерами описаны в схеме OpenAPI.

| Код | Когда | Тело |
| --- | --- | --- |
| 401 | задан `CQA_ACCESS_TOKEN`, а токена нет | `{"detail": "Нужен вход по ссылке с токеном"}` |
| 404 | нет диалога или запуска | `{"detail": "Диалог crm-2026-000123 не найден"}` |
| 409 | идёт другой запуск; диалог не сохранён | `{"detail": "Запуск 41 ещё идёт", "run_id": 41, "done": 24, "total": 80, "eta_s": 95}` |
| 409 | повтор `Idempotency-Key`, пока первый запрос идёт | `{"detail": "Запрос с Idempotency-Key crm-42 ещё выполняется: повторите позже"}` |
| 422 | поле тела не прошло проверку | `{"detail": "Запрос не прошёл проверку: dialogs.1.ch — обязательное поле", "errors": [{"path": "dialogs.1.ch", "message": "обязательное поле", "expected": "\"chat\" или \"call\""}]}` |
| 422 | тот же `Idempotency-Key` с другим телом | `{"detail": "Idempotency-Key crm-42 уже использован с другим телом запроса"}` |
| 503 | оценщик или источник не подключён | `{"detail": "Оценка моделью не подключена"}` |

После 409 из-за запуска повторите запрос через `eta_s` секунд с тем же `Idempotency-Key`.
