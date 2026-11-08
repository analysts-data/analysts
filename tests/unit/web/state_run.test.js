import { test } from 'node:test';
import assert from 'node:assert/strict';
import { S, cancelRun, failedDialogs, init, runNote, startRun } from '../../../frontend/src/lib/state.js';

const until = async (check, ms = 3000) => {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error('condition not reached');
    await new Promise(r => setTimeout(r, 20));
  }
};

test('stop keeps polling until the server says the run is over: dialogs in flight still finish', async () => {
  let status = 'running';
  const seen = [];
  globalThis.fetch = async (url, req = {}) => {
    const call = `${req.method || 'GET'} ${url}`;
    seen.push(call);
    if (call === 'POST /api/runs') return Response.json({ run_id: 1 });
    if (call === 'GET /api/runs/1') {
      return Response.json({ done: 16, total: 64, cost: 0.02, calls: 16, eta_s: 9, errors: [], status });
    }
    if (call === 'POST /api/runs/1/cancel') return Response.json({ status: 'cancelled' });
    if (call === 'GET /api/state') return Response.json({ dialogs: [] });
    throw new Error(call);
  };
  init('/api');
  await startRun({ dialogs: null, criteria: null });
  await until(() => seen.includes('GET /api/runs/1'));
  await cancelRun();
  assert.equal(S.run.status, 'running');
  assert.ok(!seen.includes('GET /api/state'));

  status = 'cancelled';
  await until(() => seen.includes('GET /api/state'));
  assert.equal(S.run.status, 'cancelled');
});

const ERRORS = ['p1-ru-003: Нет записи ответа модели', 'call-024/04: нет ответа модели, ждёт оценки', 'call-024/09: нет ответа модели, ждёт оценки'];

test('failedDialogs: dialog ids from run errors, once each, in order', () => {
  assert.deepEqual(failedDialogs(ERRORS), ['p1-ru-003', 'call-024']);
});

test('runNote: how a finished run ended, errors first', () => {
  assert.equal(runNote({ status: 'done', done: 16, total: 16, errors: [] }), 'Оценка завершена: оценено 16 из 16 ответов по критериям.');
  assert.equal(runNote({ status: 'cancelled', done: 4, total: 16, errors: [] }), 'Оценка остановлена: оценено 4 из 16 ответов по критериям.');
  assert.equal(runNote({ status: 'done', done: 16, total: 16, errors: ERRORS }),
    'Оценка завершена с ошибками: 3, в диалогах: 2. Эти ответы ждут оценки, итог считается без них.');
  assert.equal(runNote({ status: 'done', done: 0, total: 0, errors: [] }), 'Оценивать нечего: все ответы по текущему чек-листу уже есть.');
});
