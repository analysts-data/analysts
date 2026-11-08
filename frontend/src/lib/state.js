// Состояние приложения: данные GET /api/state как есть, состояние интерфейса и действия, вызывающие API.
import { createApi } from './api.js';

export const S = {
  r: null, loading: true, error: null,
  checklist: null, versions: [], dialogs: [], appeals: [], owners: {}, mode: null, llmMode: null, source: null,
  role: 'qa', q: '', open: {}, run: null, toast: null,
};

export let api = createApi('/api');
export const init = base => { api = createApi(base); };

export const render = focus => S.app?.render(focus);

export async function reload() {
  try {
    Object.assign(S, await api.getState(), { error: null });
  } catch (e) {
    S.error = e.message;
  }
  S.loading = false;
  render();
}

// Уведомление: React-компонент Toast показывает S.toast (id растёт, чтобы повтор того же текста был виден).
export function toast(msg) {
  S.toast = { msg, id: (S.toast?.id ?? 0) + 1 };
  render();
}

async function addDataset(request) {
  try {
    const { added, skipped } = await request;
    toast(`Набор загружен: добавлено ${added}, пропущено ${skipped}.`);
    await reload();
  } catch (e) {
    toast(`Набор не загружен: ${e.message}`);
  }
}
export const postDataset = groupId => addDataset(api.postDataset(groupId));
export const uploadDataset = file => addDataset(api.uploadDataset(file));
export const saveSource = (url, groupId) => addDataset(api.putSource(url, groupId));

// Ошибки запуска приходят строками «<диалог>: …» или «<диалог>/<критерий>: …» (src/cqa/services/runs.py).
export const failedDialogs = errors => [...new Set(errors.map(e => e.split(/[/:]/)[0]))];

// Итог законченного запуска одной фразой: toast, панель очереди, баннер чек-листа.
export function runNote(run) {
  const n = run.errors.length, head = run.status === 'cancelled' ? 'Оценка остановлена' : 'Оценка завершена';
  if (n) return `${head} с ошибками: ${n}, в диалогах: ${failedDialogs(run.errors).length}. Эти ответы ждут оценки, итог считается без них.`;
  if (!run.total) return 'Оценивать нечего: все ответы по текущему чек-листу уже есть.';
  return `${head}: оценено ${run.done} из ${run.total} ответов по критериям.`;
}

// localStorage может быть недоступен (приватный режим, песочница iframe): каждое обращение — в try/catch.
const RUN_KEY = 'cqa.run';
const storedRun = () => { try { return globalThis.localStorage?.getItem(RUN_KEY) ?? null; } catch { return null; } };
const rememberRun = id => { try { globalThis.localStorage?.setItem(RUN_KEY, String(id)); } catch { /* без хранилища — без переживания перезагрузки */ } };
const forgetRun = () => { try { globalThis.localStorage?.removeItem(RUN_KEY); } catch { /* без хранилища */ } };

// Единственная реализация запуска оценки: POST /api/runs, опрос раз в секунду до done или cancelled, затем reload.
export async function startRun({ dialogs, criteria }) {
  try {
    const { run_id } = await api.postRun({ dialogs, criteria });
    rememberRun(run_id);
    S.run = { id: run_id, done: 0, total: 0, cost: 0, calls: 0, eta_s: null, errors: [], status: 'running' };
    toast('Оценка запущена.');
    render();
    setTimeout(poll, 400); // первый опрос не сразу: «Оценка запущена» успевает показаться до итога короткого прогона
  } catch (e) {
    toast(`Оценка не запущена: ${e.message}`);
  }
}

async function poll() {
  const run = S.run;
  if (!run || run.status !== 'running') return;
  try {
    Object.assign(run, await api.getRun(run.id));
  } catch (e) {
    forgetRun();
    S.run = null;
    toast(`Прогресс оценки недоступен: ${e.message}`);
    return render();
  }
  render();
  if (run.status === 'running') return setTimeout(poll, 1000);
  forgetRun();
  toast(runNote(run));
  await reload();
}

// После перезагрузки страницы: running — прогресс снова на экране и опрос продолжается;
// запуск завершён или неизвестен серверу — ключ удаляется молча, без toast.
export async function resumeRun() {
  const id = storedRun();
  if (!id) return;
  try {
    const r = await api.getRun(id);
    if (r.status !== 'running') return forgetRun();
    S.run = { id, ...r };
    render();
    setTimeout(poll, 1000);
  } catch {
    forgetRun();
  }
}

// Диалоги в полёте после отмены ещё дописываются: статус и reload приходят из опроса, а не из ответа cancel.
export async function cancelRun() {
  if (!S.run) return;
  try {
    await api.cancelRun(S.run.id);
  } catch (e) {
    toast(`Оценка не остановлена: ${e.message}`);
  }
}
