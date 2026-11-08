# Порты между треками

Единственный источник имён на стыках треков. Форма данных и HTTP — в `design/contract.md`, здесь всё остальное, что читают два трека и больше. Файлы `src/cqa/domain/models.py`, `src/cqa/services/ports.py`, `src/cqa/services/errors.py`, `src/cqa/settings.py` и скелет `create_app` создаёт `bootstrap-harness` дословно по этому файлу, поэтому треки волны 1 импортируют их из `main` с первой задачи. Меняет файл только оркестратор.

## Типы и протоколы

```python
# src/cqa/domain/models.py — bootstrap-harness: модели контракта и служебные типы
class Cost(BaseModel):            # Dialog.cost
    calls: int; verifier_calls: int; usd: float; ms: int
class Mode(BaseModel):            # mode в GET /api/state
    where: Literal["kz", "local", "external"]; anonymized: bool; model: str
    verifier: Literal["jev"] | None

@dataclass(frozen=True)
class IngestResult:
    dialogs: list[Dialog]         # один на id, порядок источника, без res и reviewed
    audio: dict[str, str]         # id звонка → audio_url; в колонку dialogs.audio_url, не в Dialog
    skipped: int                  # битые записи, == len(errors)
    errors: list[str]             # "<conversation_id>: <причина>"

@dataclass(frozen=True)
class Evaluation:
    cid: str
    result: CriterionResult

@dataclass(frozen=True)
class DialogEvaluation:
    results: list[Evaluation]     # по одному на критерий с ответом, в порядке аргумента criteria
    verifier_calls: int           # запросов второго мнения за этот вызов (0 или 1)
    verifier_usd: float           # их цена; в CriterionResult.cost не входит

# src/cqa/services/ports.py — bootstrap-harness
class DialogSource(Protocol):     # реализует OrgDialogSource (dialog-ingest)
    async def fetch(self, group_id: str, url: str | None = None) -> IngestResult: ...  # Invalid | Upstream; url важнее CQA_ORG_API_URL
    def upload(self, raw: bytes) -> IngestResult: ...              # Invalid
    async def audio_link(self, audio_url: str) -> str | None: ...  # свежий MP3 из плеера; None — не вышло

class Evaluator(Protocol):        # реализует LlmEvaluator (llm-evaluation)
    async def evaluate(self, dialog: Dialog, checklist: Checklist,
                       criteria: Sequence[Criterion]) -> DialogEvaluation: ...
```

| Имя | Модуль, владелец | Сигнатура и смысл |
| --- | --- | --- |
| `LlmEvaluator.evaluate` | `src/cqa/services/evaluation.py`, llm-evaluation | как `Evaluator.evaluate`. Без кэша: два одинаковых вызова — два запроса. Исключение = сбой всего диалога. `LlmEvaluator(..., sends_real_data: bool = llm_mode == "live", allow_real_data: bool, ...)`: звонок при `sends_real_data` без `allow_real_data` → `RealDataBlocked` |
| `Verifier`, `Verdict` | `src/cqa/services/evaluation.py`, llm-evaluation | `async verify(dialog_text: str, rules: str, criteria: Sequence[Criterion]) -> Verdict`; `Verdict(answers: dict[str, str \| int \| dict[str, bool]], cost: float)`. Выключено — `None` |
| `anonymize` | `src/cqa/domain/anonymize.py`, llm-evaluation | `anonymize(dialog: Dialog) -> Dialog`: новый объект, `n`, `who`, `seg`, `t`, `s`, `fold` не меняются |
| `build_source` | `src/cqa/compose.py`, dialog-ingest | `build_source(settings: Settings) -> OrgDialogSource`, не ходит в сеть |
| `build_evaluator` | `src/cqa/compose.py`, llm-evaluation | `build_evaluator(settings: Settings) -> LlmEvaluator`, не бросает; `ConfigError` — при `evaluate` |
| `parse_payload`, `ingest_records` | `src/cqa/domain/ingest.py`, dialog-ingest | чистая пара для снимка: `ingest_records(records, *, group_id, now, shift_s, shift_paused_s) -> IngestResult` |
| `Runner` | `src/cqa/services/runs.py`, review-workflow | `Runner(store: Store, evaluator: Evaluator, *, parallel: int, clock: Callable[[], float] = time.time)` |
| `Runner.start` | там же | `start(dialogs: list[str] \| None, criteria: list[str] \| None, *, force: bool = False, confirm: bool = False, model: str \| None = None, apply: "replace" \| "compare" = "replace", override: Mapping \| None = None, evaluator: Evaluator \| None = None) -> int` — `evaluator` только на этот запуск (`run_settings` + `build_evaluator` в `http/api.py`), `override` и `compare` включают `force`; `NotFound`, `Conflict` при активном запуске, `Invalid` — `force` без списка больше `CONFIRM_OVER = 5` диалогов без `confirm` |
| `Runner.progress` | там же | `progress(run_id: int) -> dict` = `{done, total, cost, calls, eta_s, errors, status, skipped, dialogs}`; `NotFound` |
| `plan_run`, `plan_rerun` | там же | `plan_run(store, checklist, dialogs, criteria) -> Plan` — пары без текущего результата; `plan_rerun(...) -> tuple[Plan, dict[str, int]]` — все выбранные пары, кроме тех, что держит человек (ручной ответ, апелляция или решение текущего смысла), и диалог → число таких пар |
| `list_runs`, `compare_runs` | там же | `GET /api/runs`, `GET /api/runs/compare`; чистое сравнение — `compare_answers(a, b, checklist)` в `src/cqa/domain/agreement.py` |
| `history`, `restore`, `adopt` | `src/cqa/services/history.py`, review-workflow | `GET /api/dialogs/{id}/history`, `POST /api/results/{id}/restore`, `POST /api/runs/{id}/adopt`; `NotFound`, `Conflict` |
| `run_settings` | `src/cqa/services/llm_config.py` | `run_settings(settings, override) -> Settings`: режим одного запуска поверх текущего, `Invalid` с именем поля; сохранённый режим не меняется |
| `held_by_human` | `src/cqa/services/runs.py` | `(store, checklist, dialogs) -> (dialog, cid) -> bool`: ручной ответ, апелляция или решение текущего смысла — модель пару не перезаписывает (`plan_rerun`, `adopt`) |
| `Runner.use` | там же | `use(evaluator: Evaluator) -> None`: оценщик для следующих запусков (`PUT /api/config`); `Conflict` при активном запуске |
| `set_answer` | `src/cqa/services/answers.py`, review-workflow | `set_answer(store, *, dlg, cid, a, reason, by) -> CriterionResult`, `model = MANUAL = "вручную"`; `NotFound`, `Invalid`, `Conflict` |
| `configure`, `effective`, `view`, `config_error` | `src/cqa/services/llm_config.py`, llm-evaluation | режим оценки из интерфейса: `Store.overrides()` поверх `Settings`; `create_app` применяет их при старте |
| `Runner.cancel` | там же | `cancel(run_id: int) -> dict` = `{"status": "cancelled"}`; `NotFound`; `Conflict`, если запуск уже завершён |
| `Store.add_dialogs` | `src/cqa/adapters/store.py`, review-workflow | `add_dialogs(dialogs: Sequence[Dialog], audio: Mapping[str, str]) -> tuple[int, int]` — `(added, дубли по id)` |
| `Store.set_operator`, `Store.set_operators` | там же, eval-and-delivery | `set_operator(dialog_id, operator: str \| None)` — `KeyError` для неизвестного id; `set_operators(pairs: Sequence[tuple[str, str \| None]]) -> tuple[int, list[str]]` — `(обновлено, неизвестные id)` одной транзакцией |
| `Store.audio_url` | там же | `audio_url(dialog_id: str) -> str \| None`; `None` для чата и неизвестного id. Читает роутер `/audio` |

`Runner`: диалоги идут в переданном порядке (`null` — порядок добавления), не больше `parallel = settings.llm_max_parallel` диалогов одновременно, следующий берётся только после освобождения места. `cancel`: новые диалоги не берутся, диалоги в полёте завершаются и сохраняются. Возобновление — новый `POST /api/runs`: план берёт только пары без текущего результата. Повторная проверка — `force: true` (`plan_rerun`). Каждый результат запуска пишется с `run_id`; статус диалога (`run_dialogs`) — `queued` при старте, `evaluating` перед `evaluate`, `done` или `error` после, `cancelled` при отмене и `cancel_stale_runs`.

## Правила, которые держат несколько треков

| Правило | Кто пишет | Кто читает |
| --- | --- | --- |
| Звонок: `t = s`; если `s is None`, `t` — секунды от первого события транскрипта, до 0,1. `fold.t0`, `fold.t1` — `t` первой и последней реплики участка | dialog-ingest | cqa-web-ui, llm-evaluation (отрисовка) |
| `skipped` в `{added, skipped}` = дубли по id + `IngestResult.skipped`; причины пишет в журнал `cqa.ingest` источник, `review-workflow` не дублирует | dialog-ingest, review-workflow | cqa-web-ui |
| `dup: true` ставится на вторую из пары соседних реплик с той же ролью и нормализованным текстом; на первой поля нет | dialog-ingest | cqa-web-ui |
| Канал: критерий с `channel` `chat` или `call` обязан иметь `na: true`, иначе `PUT /api/checklist` → 422 (`save_checklist`). На диалоге другого канала `LlmEvaluator` — единственное место — даёт `a: "na"`, `why: "Критерий для другого канала"`, `calls: 0` без вызова модели и второго мнения; `Runner` критерии не отсеивает | review-workflow, llm-evaluation | cqa-web-ui |
| Флаг: `a[k] = основная[k] or второе_мнение[k]`, `alt` — ответ второго мнения как есть. Флаг возвращается всегда: упавший подвопрос (429 после повторов, не разобран, нет ответа Jev) считается «не найдено», найденное сохраняется, у флага `evFail: true`. `violation_found: true` требует `turn_ids` с `quote`; `seg` флага — из `checked_range` первого найденного или пусто | llm-evaluation | review-workflow (`needs_review` для флага всегда `False`), cqa-web-ui |
| `CriterionResult`: `calls` — вызовы основной модели с повторами, `cost` — только их цена, `ms` — сумма длительностей HTTP | llm-evaluation | review-workflow |
| `Dialog.cost` пишет `Runner` после каждого `evaluate` диалога: `calls = Σ result.calls`, `verifier_calls`, `usd = Σ result.cost + verifier_usd`, `ms` — время вызова `evaluate` по часам `Runner`. Та же цена идёт в `cost` запуска | review-workflow | cqa-web-ui, eval-and-delivery (README, `demo.py`) |
| Повтор ответа — по отпечатку `fingerprint(checklist, criterion, ch)` = sha256[:16] от `rules` и полей `text, type, steps, stepText, na, naCond, questions, channel`, а для звонка (`ch == "call"`) ещё `call`, если он задан; `fingerprints(checklist)` — канал → id → отпечаток; модели и версии промпта в нём нет; смена сценария набор не пересчитывает. Ключа кэша в результатах нет | review-workflow | llm-evaluation, eval-and-delivery |
| `make eval` вызывает `build_evaluator(settings).evaluate` напрямую, мимо `results` и кассет | eval-and-delivery | — |

## Ошибки и коды HTTP

| Класс | Модуль | Код | Где возникает |
| --- | --- | --- | --- |
| `NotFound` | `src/cqa/services/errors.py` | 404 | неизвестный диалог, критерий, апелляция, запуск; `/audio` и `/player` для чата |
| `Invalid` | там же | 422 | недопустимый ответ, пустая причина, плохой `group_id`, файл не в формате организаторов |
| `Conflict` | там же | 409 | второй активный запуск, отмена завершённого, устаревший черновик, повторная апелляция |
| `Upstream` | там же | 502 | API организаторов не ответил или вернул ошибку; ссылку на запись получить не удалось |
| `Unavailable` | там же | 503 | источник или оценщик не подключён (`app.state.source is None`, `app.state.runner is None`) |
| `ConfigError` | там же | — | нет ключа или неизвестный профиль; бросает `evaluate`, попадает строкой в `errors` запуска |

Примеры 422 из `save_checklist`: `Критерий 05: для канала chat нужен na: true`, `Повторяется id критерия 04`.
| `ModelUnavailable`, `RealDataBlocked`, `CassetteMissing` | llm-evaluation | — | строкой `"{dialog_id}: {exc}"` в `errors` запуска |
| `PayloadError`, `OrgApiError` | dialog-ingest | — | только внутри трека: `OrgDialogSource` переводит их в `Invalid` или `Upstream` |

Обработчики в `create_app` (`bootstrap-harness`) отвечают `{"detail": str(exc)}`. Текст по-русски, с идентификатором, без адресов и подписей.

## `create_app` и `app.state`

`create_app(settings: Settings | None = None, *, source: DialogSource | None = None, evaluator: Evaluator | None = None, conn: sqlite3.Connection | None = None) -> FastAPI` — в `src/cqa/http/app.py`.

| Атрибут `app.state` | Тип | Кто кладёт |
| --- | --- | --- |
| `settings` | `Settings` | bootstrap-harness |
| `store` | `Store` | review-workflow (`conn` или `connect(settings.db_path)`) |
| `source` | `DialogSource \| None` | review-workflow кладёт аргумент; dialog-ingest заменяет `None` на `build_source(settings)` |
| `runner` | `Runner \| None` | review-workflow; `None`, пока оценщика нет. llm-evaluation заменяет `evaluator=None` на `build_evaluator(settings)` |
| `mode` | `Mode` | review-workflow (`mode_from_settings`) |
| `syncer` | `Syncer` | dialog-ingest (`src/cqa/services/sync.py`): `PUT /api/source`, `source` в состоянии; lifespan приложения запускает `Syncer.run(skip=automation.owns_sync)` |
| `automation` | `Automation` | eval-and-delivery (`src/cqa/services/automation.py`): `/api/automation*`; lifespan запускает `Automation.run()` — одна задача, тик 15 с. Внешние куски — за `Ports` (`sources`, `sync`, `evaluate`, `source_of`, `blocked`, `notify`, `audit`, `steps`); `wire()` собирает их на Syncer и Runner, реестр источников, батч-задачи, достаточность, алерты и классификация подключаются заменой одной строки в `wire()` |
| `syncer` | `Syncer` | dialog-ingest (`src/cqa/services/sync.py`): `PUT /api/source`, `source` в состоянии; lifespan приложения запускает `Syncer.run()` |
| `batches` | `Batches` | eval-and-delivery (`src/cqa/services/batches.py`, таблицы в `src/cqa/adapters/batches.py`): `/api/batches`; lifespan запускает `Batches.work()`, `create_app` — `recover()` |

| Строка в `create_app` | Трек |
| --- | --- |
| `GET /api/health`, обработчики ошибок, раздача `web/` на `/` — последней строкой, иначе статика перекроет роутеры | bootstrap-harness |
| `include_router(cqa.http.api.router)` — все пути контракта, кроме `/audio` и `/player`; сид чек-листа на пустой базе | review-workflow |
| `include_router(cqa.http.audio.router)` — `/api/dialogs/{id}/audio`, `/player` | dialog-ingest |
| `include_router(cqa.http.docs.router)` — документация `/docs/` из `docs/site/*.md` и справочник по `app.openapi()`; Swagger и ReDoc выключены, схема — `/api/openapi.json` | eval-and-delivery |

## Settings (`src/cqa/settings.py`, `CQA_*` и `.env`)

| Переменная | Поле | Тип | По умолчанию | Читает |
| --- | --- | --- | --- | --- |
| `CQA_LLM_MODE` | `llm_mode` | `Literal["replay", "record", "live"]` | `replay` | llm-evaluation, eval-and-delivery |
| `CQA_LLM_BASE_URL` | `llm_base_url` | `str \| None` | `None` | llm-evaluation |
| `CQA_LLM_API_KEY` | `llm_api_key` | `SecretStr \| None` | `None` | llm-evaluation |
| `CQA_LLM_MODEL` | `llm_model` | `str` | `qwen3-6` | llm-evaluation, review-workflow (`mode`) |
| `CQA_LLM_PROFILE` | `llm_profile` | `str` | `plain` | llm-evaluation |
| `CQA_LLM_REASONING` | `llm_reasoning` | `Literal["on", "off"]` | `on` | llm-evaluation |
| `CQA_LLM_MAX_PARALLEL` | `llm_max_parallel` | `int` | `4` | llm-evaluation (семафор), review-workflow (`Runner.parallel`) |
| `CQA_LLM_RPM` | `llm_rpm` | `int` | `120` (`0` — без лимита) | llm-evaluation, eval-and-delivery (`rate_limit` в `/api/batches`) |
| `CQA_LLM_TIMEOUT_S` | `llm_timeout_s` | `float` | `180` | llm-evaluation |
| `CQA_LLM_PRICE_IN`, `CQA_LLM_PRICE_OUT` | `llm_price_in`, `llm_price_out` | `float` | `0.0` (USD за 1 млн токенов) | llm-evaluation |
| `CQA_VERIFIER` | `verifier` | `Literal["jev"] \| None` | `None` (пусто) | llm-evaluation, review-workflow (`mode`) |
| `CQA_JEV_API_KEY` | `jev_api_key` | `SecretStr \| None` | `None` | llm-evaluation |
| `CQA_ANONYMIZE` | `anonymize` | `bool` | `True` | llm-evaluation, review-workflow (`mode`) |
| `CQA_DATA_WHERE` | `data_where` | `Literal["kz", "local", "external"]` | `kz` | review-workflow (`mode`) |
| `CQA_ALLOW_REAL_DATA` | `allow_real_data` | `bool` | `False`, ставит только человек | llm-evaluation, eval-and-delivery |
| `CQA_ORG_API_URL` | `org_api_url` | `SecretStr \| None` | `None` | dialog-ingest |
| `CQA_RAW_DIR` | `raw_dir` | `Path` | `data/raw` | dialog-ingest |
| `CQA_AUDIO_SHIFT_S` | `audio_shift_s` | `float` | `0.25` | dialog-ingest |
| `CQA_AUDIO_SHIFT_PAUSED_S` | `audio_shift_paused_s` | `float` | `4.5` | dialog-ingest |
| `CQA_DB_PATH` | `db_path` | `str` | `data/cqa.db` | review-workflow, eval-and-delivery (`backup`, e2e) |
| `CQA_EVAL_DATASET` | `eval_dataset` | `Path` | `data/dev.json` | eval-and-delivery |
| `CQA_HOLDOUT_DIR` | `holdout_dir` | `Path \| None` | `None` | eval-and-delivery |
| `CQA_EVAL_REPORTS_DIR` | `eval_reports_dir` | `Path` | `eval/reports` | eval-and-delivery (`GET /api/quality`) |
| `CQA_RESULTS_DIR` | `results_dir` | `Path` | `results` | eval-and-delivery (`GET /api/results`, каталог отчётов) |
| `CQA_ACCESS_TOKEN` | `access_token` | `SecretStr \| None` | `None` (пусто — без входа) | eval-and-delivery (`make share`, `src/cqa/http/access.py`) |

Значения по умолчанию — сценарий 4. Цена Jev (0,042 USD за 1 млн входных токенов) — константа в `src/cqa/adapters/jev.py`. `CQA_NOW` читает только `scripts/stop_code.sh`, в `Settings` его нет. `.env.example` содержит все поля без значений секретов.

## Хранилище (`data/cqa.db`, владелец review-workflow)

| Таблица | Колонки, которые видят другие треки | Кто ещё трогает |
| --- | --- | --- |
| `dialogs` | `id TEXT PK`, `body TEXT` (Dialog без `res`, `reviewed`, `cost`, `operator`), `reviewed INTEGER`, `audio_url TEXT NULL` (не отдаётся ни в одном ответе), `cost TEXT NULL` (JSON `Cost`, перезаписывается), `operator TEXT NULL` (сотрудник; старые базы получают колонку в `connect`) | dialog-ingest через `Store.audio_url` |
| `results` | `id INTEGER PK`, `dialog_id`, `cid`, `version`, `fp`, `body` (JSON `CriterionResult`), `created`, `run_id INTEGER NULL`, `shadow INTEGER` (1 — теневой ответ запуска `compare`, `Store.current_results` его не видит); только `INSERT` (триггеры) | — |
| `runs` | `id`, `total`, `done`, `cost`, `calls`, `errors` (JSON-список строк), `status TEXT CHECK IN ('running', 'done', 'cancelled')`, `started`, `finished`, `model TEXT NULL`, `checklist_version INTEGER NULL`, `force INTEGER`, `skipped INTEGER`, `apply TEXT` (`replace` \| `compare`), `override TEXT NULL` (JSON) | — |
| `run_dialogs` | `run_id`, `dialog_id` (PK вместе), `status CHECK IN ('queued', 'evaluating', 'done', 'error', 'skipped', 'cancelled')`, `total`, `done`, `skipped`, `error`; статус меняется (`Runner`) | — |
| `appeals` | `n INTEGER PK` (id = `"a" + n`), `dlg`, `cid`, `kind CHECK IN ('appeal', 'review')`, `fp`, `status CHECK IN ('pending', 'confirmed', 'changed', 'closed')`, `body` | — |
| `employees` | `id TEXT PK`, `name`, `role CHECK IN ('operator', 'qa', 'reviewer', 'manager', 'admin')`, `team`, `active INTEGER` | eval-and-delivery (employees-audit) |
| `audit` | `id INTEGER PK`, `at` (ISO +05:00), `actor_id NULL`, `actor_name`, `role`, `action`, `target_type`, `target_id`, `details_json`; только `INSERT` (триггеры) | пишут все треки через `record` |

Колонки, появившиеся после первых баз, перечислены в `COLUMNS` (`src/cqa/adapters/store.py`): `connect` досоздаёт их в старой базе через `ALTER TABLE ... ADD COLUMN`, прежние строки получают `NULL` или умолчание. Новая колонка — строка в `COLUMNS`, схему `CREATE TABLE` не трогать.

eval-and-delivery берёт файл базы только целиком (`make backup`, временный `CQA_DB_PATH` в e2e) и схему не читает.

## Интерфейс

`web/js/scoring.js` (cqa-web-ui), чистый модуль, импортируют analytics-coaching, e2e и `node --test`:

| Экспорт | Сигнатура | Возвращает |
| --- | --- | --- |
| `r2` | `r2(x: number)` | округление до 2 знаков, половина вверх через десятичную запись: `r2(1.005) == 1.01`, `r2(0.285) == 0.29` |
| `frac` | `frac(criterion, answer)` | `1`, `0`, `ступень / max(steps)`, `null` для `na`, `null` (нет записи) и флага |
| `ans` | `ans(dialog, cid, appeals)` | `null`, если записи в `res` нет; иначе `to` последней в порядке `appeals` записи пары (`appeal` или `review`) со статусом `confirmed` или `changed`, иначе `res[cid].a`. То же правило, что `from` у сервера (`effective_answer`) |
| `calc` | `calc(dialog, checklist, appeals, override = null)` | `{total, W, G, pending, rows, secs, losses}`; `total` — `null`, если применимых с весом нет; `pending` — число критериев без записи; `override = {cid, val}` |
| `flagsOf` | `flagsOf(dialog, checklist)` | подписи найденных нарушений |

Клиент `web/js/api.js`: `createApi(base, fetchFn)` с методами по контракту, в том числе `postRun({dialogs, criteria})` (диалоги в порядке очереди), `getRun(id)`, `cancelRun(id)`, `postReview(...)` → `POST /api/decisions`. Запуск — одно действие `startRun` в `state.js`, опрос до `status` `done` или `cancelled`. Время реплики звонка на экране — `t`; `fold` рисуется одной строкой с кнопкой раскрытия, реплики участка остаются в `lines`.

Атрибуты для e2e (имена `data-act` уникальны на всё приложение):

| Шаг защиты | Селектор |
| --- | --- |
| Роль | `[data-act="role"][data-role="qa" \| "operator" \| "reviewer"]` |
| Экраны | контейнер `[data-view="<page>"]`, страницы `queue`, `appeals`, `checklist`, `analytics`, `coaching` |
| Список | строка `[data-act="open"][data-id="<dialog id>"]` |
| Карточка | критерий `[data-cid]`, «К реплике» `[data-act="ev"][data-n]`, реплика `[data-n]`, «Перейти к фрагменту» `[data-act="seek"][data-n]`, «Оставить»/«Принять» второго мнения `[data-act="review"][data-cid]`, отметка `[data-act="reviewed"]` |
| Апелляция | «Оспорить оценку» `[data-act="appeal"][data-cid]`; «Сохранить решение» на `#/appeals` `[data-act="decide"]`, неактивна без причины |
| Замена критерия | «Сохранить как vN» `[data-act="csave"]`, «Оценить набор» `[data-act="crun"]`, «Остановить» `[data-act="stop"]` |

Папки e2e: `tests/e2e/web/` — тесты экранов cqa-web-ui и analytics-coaching (статический сервер `web_url`, `page.route` на `tests/fixtures/state_prototype.json`); `tests/e2e/defence/` — сценарий защиты eval-and-delivery (`uvicorn` в подпроцессе, `replay`). Общих `autouse`-фикстур в `tests/e2e/conftest.py` нет, все файлы помечены `pytest.mark.e2e`.

## Make, фикстуры, кассеты

| Цель | Что делает | Параметры |
| --- | --- | --- |
| `make check` | ruff, mypy, pytest без сети, `node --test`, секреты, защищённые пути, стоп-код; локально `openspec validate --all --strict` | — |
| `make run` | `uvicorn` на `127.0.0.1:8000` | `.env` |
| `make share` | `uvicorn` на `0.0.0.0:$(PORT)` с `CQA_ACCESS_TOKEN` (пустой — новый `secrets.token_urlsafe(16)`), печатает `http://<IP>:$(PORT)/login?token=…` | `PORT=8000` |
| `make record` | `CQA_LLM_MODE=record uv run pytest -m "cassette or e2e"`: перезаписывает ровно те вызовы, что потом проигрываются, только на синтетике прототипа (`call-024` тоже синтетика) | без параметров: набор и чек-лист — фикстуры тестов. Запускает агент с ключом в `.env` от человека; `CQA_ALLOW_REAL_DATA` не нужен (в `record` звонки не блокируются) |
| `make e2e` | `uv run pytest -m e2e`, сервер в подпроцессе с `CQA_LLM_MODE` из окружения (по умолчанию `replay`) | `ARGS=--runxfail` |
| `make eval` | `CQA_LLM_MODE=live uv run python -m cqa.services.quality_eval $(ARGS)` | `ARGS="--checklist PATH"`, `ARGS=--accept` |
| `make eval-holdout` | то же с `--holdout` | `CQA_HOLDOUT_DIR` вне репозитория |
| `make backup` | `scripts/backup_db.py` → `data/backup/cqa-<HHMM>.db` | `CQA_DB_PATH` |

| Файл | Формат | Владелец |
| --- | --- | --- |
| `tests/fixtures/checklist_v3.json` | `Checklist` (`CL0` прототипа) | bootstrap-harness |
| `tests/fixtures/dialogs_prototype.json` | `list[Dialog]` с `res` (`D` прототипа) | bootstrap-harness |
| `tests/fixtures/scoring_vectors.json` | `[{name, checklist, answers: {cid: a}, total}]`, `total: number \| null` | bootstrap-harness |
| `tests/fixtures/org_payload.json` | конверт организаторов `{error, isSuccess, data: {dataset_group_id, total_records, records}}`, 5 записей `syn-*` | dialog-ingest |
| `tests/e2e/fixtures/defence_set.json` | тот же конверт, 8 синтетических диалогов прототипа | eval-and-delivery |
| `tests/e2e/fixtures/replacement_criterion.json` | один `Criterion` | eval-and-delivery |
| `tests/fixtures/state_prototype.json` | ответ `GET /api/state` на данных прототипа | cqa-web-ui |
| `tests/cassettes/{llm,jev}/{sha}.json` | `{"request": тело, "status": код, "response": JSON}`, без заголовков; `sha = sha256(json.dumps(тело, ensure_ascii=False, sort_keys=True, separators=(",", ":")))` | llm-evaluation |

## Провайдеры моделей (llm-evaluation)

Дополняет таблицы выше; форма HTTP — раздел «Провайдеры моделей» в `design/contract.md`.

| Имя | Где | Смысл |
| --- | --- | --- |
| `CQA_LLM_PROVIDER` → `llm_provider` | `Settings`, `str`, `env` | код основной модели; `effective` переносит поля провайдера в `llm_base_url`, `llm_model`, `llm_profile`, `llm_api_key`, `data_where` |
| `CQA_PROVIDERS` → `providers` | `Settings`, `dict[str, Provider]`, `{}` | JSON `{код: {label, base_url, model, profile, where, key}}`; `effective` добавляет `env`, список из базы (`overrides["providers"]`) заменяет этот |
| `CQA_OPENROUTER_API_KEY` → `openrouter_api_key` | `Settings`, `SecretStr \| None`, `None` | ключ встроенного провайдера `openrouter-jev`; `effective` добавляет его вторым после `env` |
| `CQA_VERIFIER` → `verifier` | `Settings`, `str \| None` | `"jev"` или код провайдера; `Mode.verifier` — `str \| None` |
| `Provider` | `src/cqa/settings.py` | `label`, `base_url: str \| None`, `model`, `profile`, `where`, `key: SecretStr \| None` |
| `put_provider`, `delete_provider`, `provider`, `as_llm` | `src/cqa/services/llm_config.py` | `put_provider(store, settings, pid, body, apply)`, `delete_provider(store, settings, pid, apply)` -> `Settings`, как `configure`; `provider(settings, pid)` — `NotFound`; `as_llm(provider)` — поля основной модели |
| `ChatVerifier` | `src/cqa/services/evaluation.py` | `Verifier` на `ChatModel` провайдера: те же запросы по критериям без повтора; `build_evaluator` собирает его, если `verifier` — код провайдера |
| `check_provider`, `ping` | `src/cqa/compose.py`, `src/cqa/adapters/llm.py` | `POST /api/providers/{id}/check`: `{ok, ms, error}` мимо записей |

## Режим «только Jev» (llm-evaluation, jev-only)

| Имя | Модуль | Сигнатура и смысл |
| --- | --- | --- |
| `JevEvaluator` | `src/cqa/services/evaluation.py` | реализует `Evaluator`: `JevEvaluator(jev: Verifier, *, model_name, anonymize, sends_real_data, allow_real_data, config_error=None)`; один `verify` на диалог по критериям его канала; ошибка Jev — сбой всего диалога |
| `Verdict.confidence` | там же | `dict[str, float]`, по умолчанию пусто: id критерия → вероятность ответа Jev, у флага наименьшая по подвопросам |
| `JEV_SURE` | там же | `0.6`: вероятность ниже или её нет — `evFail` |
| `JEV_MODEL` | `src/cqa/adapters/jev.py` | `"jev-latest"`: модель запроса и `mode.model` в режиме jev |
| `build_evaluator` | `src/cqa/compose.py` | `-> Evaluator`: `JevEvaluator` при `settings.evaluator == "jev"`, иначе `LlmEvaluator` |
| `byJev` | `web/js/queue.js` | `byJev(resultOrMode)`: `model` начинается с `jev`; карточка и очередь пишут «Jev не уверен в ответе» вместо «Цитата не нашлась» и не называют проверенный участок |

Settings: `CQA_EVALUATOR` → `evaluator: Literal["llm", "jev"] = "llm"`, читают llm-evaluation, review-workflow (`mode`), eval-and-delivery (`make eval`, `scenario.evaluator` в `eval/baseline.json`). Правило канала: на диалоге другого канала `na` с `why: "Критерий для другого канала"` даёт и `JevEvaluator`, без вопроса Jev.

## Интонация звонка (dialog-ingest, prosody)

```python
# src/cqa/services/ports.py
class Voice(Protocol):            # реализует PraatVoice (src/cqa/adapters/voice.py)
    async def tracks(self, link: str) -> Tracks | None: ...  # None — запись не скачалась или не разобралась
```

| Имя | Модуль | Сигнатура и смысл |
| --- | --- | --- |
| `Tracks` | `src/cqa/domain/prosody.py` | кадры по 10 мс: `pitch_t`, `f0` (Гц, 0 — тона нет), `int_t`, `db` |
| `analyse` | там же | `analyse(lines: Sequence[Line \| Fold], tracks: Tracks) -> dict` — тело ответа `/prosody`, чистая функция |
| `utterance_s` | `src/cqa/domain/audio_timeline.py` | `utterance_s(text) -> float`: оценка длительности реплики, общая для `s` и интонации |
| `dialog_prosody` | `src/cqa/services/prosody.py` | `async dialog_prosody(store, source, voice, dialog_id) -> dict`; `NotFound`, `Upstream`; база — только в потоке цикла событий, разбор звука — в `asyncio.to_thread` внутри `PraatVoice` |
| `Store.prosody`, `Store.set_prosody` | `src/cqa/adapters/store.py` | `prosody(dialog_id) -> dict \| None`, `set_prosody(dialog_id, body)` |
| `app.state.voice` | `create_app` | `PraatVoice(httpx.AsyncClient())`; тесты подменяют подделкой с синтетическими кадрами |
| Таблица `prosody` | `data/cqa.db` | `dialog_id TEXT PK REFERENCES dialogs(id)`, `body TEXT` (JSON ответа) |
| `ffmpeg` | системная зависимость сервера | в `PATH`; без него `/prosody` отвечает 502, остальное работает |
| `Prosody` | `src/cqa/services/evaluation.py` | `Callable[[str], Awaitable[Mapping[str, Any]]]`: id звонка → тело `/prosody`, исключение — разбора нет; `LlmEvaluator`/`JevEvaluator(..., prosody=None)`, `build_evaluator(settings, prosody=None)`; сервер — `app.state.prosody` (`dialog_prosody` с текущими `source`, `voice`) |
| `dialog_prosody(..., fresh=True)` | `src/cqa/services/prosody.py` | считать заново и перезаписать сохранённый разбор; `/talkstats` — для разбора без `talk` |
| `Span`, `call_stats`, `chat_stats`, `norms`, `mark`, `CALL`, `CHAT`, `RULE` | `src/cqa/domain/talkstats.py` | статистика разговора, чистые функции: `call_stats(spans) -> dict` (поле `talk` разбора), `chat_stats(lines) -> dict \| None`, `norms(rows, metrics) -> Norms`, `mark(stats, norms) -> list` |
| `dialog_talkstats`, `team_norms` | `src/cqa/services/talkstats.py` | `async dialog_talkstats(store, source, voice, dialog_id) -> dict`, `team_norms(store) -> dict`; `NotFound`, `Upstream` |
| `Store.prosodies` | `src/cqa/adapters/store.py` | `prosodies() -> dict[str, dict]`: все сохранённые разборы по id звонка для норм |

Атрибуты для e2e: панель `[data-prosody="on"]`, строка `[data-prosody="off"]` (502) и `[data-prosody="loading"]`, значок у реплики `#tr [data-n] .pros`. Тесты экранов подменяют `/prosody` пустым ответом (`tests/e2e/web/conftest.py`), сценарий защиты — тоже.

## Текущий сотрудник и журнал действий (eval-and-delivery, employees-audit)

| Функция | Где | Что делает |
| --- | --- | --- |
| `actor_from(request, sign="") -> Actor` | `src/cqa/http/actor.py` | активный сотрудник из `X-CQA-User`; иначе `Actor(None, sign or "без входа")` |
| `signed(actor, sign) -> str` | `src/cqa/http/actor.py` | подпись записи (`by`, `reviewer`): имя сотрудника, без входа — `sign` |
| `Actor(id: str \| None, name: str, role: str = "")` | `src/cqa/services/audit.py` | frozen dataclass |
| `record(store, actor, action, target_type, target_id, details=None) -> None` | `src/cqa/services/audit.py` | строка журнала; ключи с key/token/secret/password в `details` отбрасываются |

Каждый новый изменяющий путь и выгрузка вызывает `record` после удачного действия; `action` — `<объект>.<глагол>`, выгрузка — `export`. Имена действий и `details` — таблица в разделе контракта «Сотрудники и журнал действий».
