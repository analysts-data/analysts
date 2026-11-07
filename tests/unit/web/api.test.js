import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApi, resolveBase } from '../../../web/js/api.js';

test('resolveBase prefers the data parameter, then the attribute, then /api', () => {
  assert.equal(resolveBase('?data=https://host/api', 'https://other/api'), 'https://host/api');
  assert.equal(resolveBase('', null), '/api');
  assert.equal(resolveBase('', '/custom-api'), '/custom-api');
});

const recorder = (status = 200, body = '{}') => {
  const calls = [];
  const fetchFn = async (url, init = {}) => {
    calls.push({ method: init.method || 'GET', url, body: init.body });
    return new Response(body, { status });
  };
  return { calls, fetchFn };
};

test('every client method goes to its contract path', async () => {
  const { calls, fetchFn } = recorder();
  const api = createApi('/api', fetchFn);
  await api.getState();
  await api.postDataset('DEV');
  await api.uploadDataset('{"data": {}}');
  await api.postRun({ dialogs: ['call-024'], criteria: null });
  await api.getRun('r1');
  await api.cancelRun('r1');
  await api.putChecklist({ version: 3 });
  await api.postAppeal({ dlg: 'd', cid: 'c', ask: 20, ev: [], comment: 'текст', by: 'Оператор' });
  await api.postDecision('a1', { to: 20, reason: 'r', reviewer: 'Проверяющий' });
  await api.postReview({ dlg: 'd', cid: 'c', from: 'no', to: 'yes', reason: 'r', reviewer: 'Специалист КК' });
  await api.postReviewed('p1-ru-003', false);
  await api.putOwners({ Тег: 'Инструкция' });
  await api.putSource('https://org.test/api?token=t', 'DEV');
  const seen = calls.map(c => `${c.method} ${c.url}`);
  assert.deepEqual(seen, [
    'GET /api/state', 'POST /api/datasets', 'POST /api/datasets/upload', 'POST /api/runs', 'GET /api/runs/r1',
    'POST /api/runs/r1/cancel', 'PUT /api/checklist', 'POST /api/appeals', 'POST /api/appeals/a1/decision',
    'POST /api/decisions', 'POST /api/dialogs/p1-ru-003/reviewed', 'PUT /api/owners', 'PUT /api/source',
  ]);
  assert.deepEqual(JSON.parse(calls[1].body), { group_id: 'DEV' });
  assert.equal(calls[2].body, '{"data": {}}');
  assert.deepEqual(JSON.parse(calls[3].body), { dialogs: ['call-024'], criteria: null });
  assert.deepEqual(JSON.parse(calls[10].body), { reviewed: false });
  assert.deepEqual(JSON.parse(calls[11].body), { Тег: 'Инструкция' });
  assert.deepEqual(JSON.parse(calls[12].body), { url: 'https://org.test/api?token=t', group_id: 'DEV' });
  assert.equal(api.audioUrl('call-024'), '/api/dialogs/call-024/audio');
  assert.equal(api.playerUrl('call-024'), '/api/dialogs/call-024/player');
});

test('a non-2xx answer throws with the server text', async () => {
  const { fetchFn } = recorder(422, '{"detail": "reason is required"}');
  await assert.rejects(createApi('/api', fetchFn).postDecision('a1', {}), /reason is required/);
});
