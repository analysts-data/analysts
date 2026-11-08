# Метрики использования: клиент

Сервер — `POST /api/telemetry` и `GET /api/usage` (`design/contract.md`, раздел «Метрики использования»). Ниже весь клиент: положите в `frontend/src/track.js` (или `web/js/track.js`) как есть.

```js
// Метрики использования (POST /api/telemetry): пакет раз в 10 с, по 50 событий и при уходе со вкладки.
let queue = [], ctx = { role: null, user: null, page: null }, timer = 0, since = Date.now();
const spent = () => { const ms = Date.now() - since; since = Date.now(); return ms; };

export function track(event, props = {}) {
  queue.push({ event, at: new Date().toISOString(), page: ctx.page || 'app', props });
  if (queue.length >= 50) flush(); else timer ||= setTimeout(flush, 10000);
}

export function flush() {
  clearTimeout(timer); timer = 0;
  if (!queue.length) return;
  const url = '/api/telemetry' + (ctx.role ? `?role=${ctx.role}` : ''), body = JSON.stringify(queue.splice(0, 200));
  const headers = ctx.user ? { 'X-CQA-User': ctx.user } : {}; // sendBeacon заголовков не шлёт: с сотрудником — fetch
  if (ctx.user || !navigator.sendBeacon?.(url, body)) fetch(url, { method: 'POST', body, keepalive: true, headers }).catch(() => {});
}

export function setContext(next) { // {role, user, page}: смена экрана пишет time_on_page прошлого и page_view нового
  if (next.role && next.role !== ctx.role) flush();
  const moved = next.page && next.page !== ctx.page;
  if (moved && ctx.page) track('time_on_page', { ms: spent() });
  ctx = { ...ctx, ...next };
  if (moved) { spent(); track('page_view'); }
}

addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') { track('time_on_page', { ms: spent() }); flush(); } else spent();
});
addEventListener('click', e => { const el = e.target.closest?.('[data-act]'); if (el) track('action', { act: el.dataset.act, id: el.dataset.id }); });
```

Подключение:

- Роутер: `useEffect(() => setContext({ page }), [page])`; переключатель роли: `setContext({ role })`; вошедший сотрудник: `setContext({ user: employeeId })` (то же значение, что `X-CQA-User` в `createApi`). Все клики по `[data-act]` уходят событием `action` сами.
- Остальное — явным вызовом в обработчике:

| Событие | Где | props |
| --- | --- | --- |
| `dialog_open` | карточка открыта | `{id: dialogId}` |
| `appeal_submit` | апелляция подана | `{id: dialogId, cid}` |
| `appeal_open` | апелляция открыта на `#/appeals` | `{id: appealId}` |
| `decision_submit` | решение сохранено | `{id: appealId}` |
| `search` | поиск в очереди | `{len: q.length, has_result: rows.length > 0}` — сам текст не отправляем |
| `filter` | фильтр очереди | `{name: 'risk', value: 'on'}` |
| `checklist_save`, `run_start` | сохранение версии, запуск оценки | `{n}` по желанию |
| `export`, `report_open` | файл чек-листа, отчёт | `{kind: 'checklist-csv'}`, `{kind: 'html'}` |
| `help_open` | открыта подсказка | `{id: 'mode'}` |
| `error_shown` | показана ошибка | `{code: 'run_failed'}` — код, не текст |

Сервер принимает в `props` только ключи `act`, `id`, `cid`, `ms`, `len`, `has_result`, `name`, `value`, `kind`, `format`, `code`, `n` со значением-числом, bool или словом без пробелов; остальное молча отбрасывает. `page` — слово без пробелов (`queue`, `card`, `appeals`, …).
