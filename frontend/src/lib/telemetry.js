// Метрики взаимодействия: события пачками в POST /api/telemetry (design/contract.md). Без текста диалогов и поисковых строк.
// sendBeacon не передаёт X-CQA-User, поэтому fetch с keepalive.
import { S, api, userHeader } from './state.js';

const Q = [];
let timer;

// экран по контракту (^\w[\w.:/#-]{0,63}$): analytics, d, queue — без #/ и без id
const screen = () => (globalThis.location?.hash.split('?')[0] ?? '').replace(/^#\/?/, '').split('/')[0] || 'queue';

export function track(event, props = {}, page = screen()) {
  if (!S.features?.includes('telemetry')) return; // сервер без сбора метрик
  Q.push({ event, at: new Date().toISOString(), page: page || 'queue', props });
  if (Q.length >= 20) flush();
  else {
    clearTimeout(timer);
    timer = setTimeout(flush, 3000);
  }
}

// Успешные запросы, из которых складываются воронки экрана «Использование» (domain/usage.py, FUNNELS):
// props.id — диалог у appeal_submit, апелляция у decision_submit; строкой, как в dialog_open и appeal_open.
const SENT = [
  ['POST', /^\/appeals$/, 'appeal_submit', b => b?.dlg],
  ['POST', /^\/appeals\/([^/?]+)\/decision$/, 'decision_submit', (b, m) => decodeURIComponent(m[1])],
  ['PUT', /^\/checklist$/, 'checklist_save'],
  ['POST', /^\/runs$/, 'run_start'],
];

export function sent(method, path, body) {
  for (const [m, re, event, idOf] of SENT) {
    const x = method === m && path.match(re);
    if (x) return track(event, idOf ? { id: String(idOf(body, x) ?? '') } : {});
  }
}

export function flush() {
  if (!Q.length) return;
  const body = JSON.stringify(Q.splice(0, 200));
  try {
    globalThis.fetch(`${api.base}/telemetry`, { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', ...userHeader() }, body }).catch(() => {});
  } catch {
    /* метрики не мешают работе */
  }
}

globalThis.addEventListener?.('visibilitychange', () => {
  if (globalThis.document?.visibilityState === 'hidden') flush();
});
