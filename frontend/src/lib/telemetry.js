// Метрики взаимодействия: события пачками в POST /api/telemetry (design/contract.md). Без текста диалогов и поисковых строк.
// sendBeacon не передаёт X-CQA-User, поэтому fetch с keepalive.
import { api, userHeader } from './state.js';

const Q = [];
let timer;

export function track(event, props = {}) {
  Q.push({ event, at: new Date().toISOString(), page: globalThis.location?.hash.split('?')[0] || '#/', props });
  if (Q.length >= 20) flush();
  else {
    clearTimeout(timer);
    timer = setTimeout(flush, 3000);
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
