import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApi, resolveBase } from '../../../frontend/src/lib/api.js';

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
  await api.putAnswer('p1-ru-003', '01', { a: 'no', reason: 'r', by: 'Специалист КК' });
  await api.getConfig();
  await api.putConfig({ llm_model: 'm' });
  await api.putProvider('ds', { label: 'DS' });
  await api.deleteProvider('ds');
  await api.checkProvider('ds');
  const seen = calls.map(c => `${c.method} ${c.url}`);
  assert.deepEqual(seen, [
    'GET /api/state', 'POST /api/datasets', 'POST /api/datasets/upload', 'POST /api/runs', 'GET /api/runs/r1',
    'POST /api/runs/r1/cancel', 'PUT /api/checklist', 'POST /api/appeals', 'POST /api/appeals/a1/decision',
    'POST /api/decisions', 'POST /api/dialogs/p1-ru-003/reviewed', 'PUT /api/owners', 'PUT /api/source',
    'PUT /api/dialogs/p1-ru-003/answers/01', 'GET /api/config', 'PUT /api/config',
    'PUT /api/providers/ds', 'DELETE /api/providers/ds', 'POST /api/providers/ds/check',
  ]);
  assert.deepEqual(JSON.parse(calls[16].body), { label: 'DS' });
  assert.deepEqual(JSON.parse(calls[1].body), { group_id: 'DEV' });
  assert.equal(calls[2].body, '{"data": {}}');
  assert.deepEqual(JSON.parse(calls[3].body), { dialogs: ['call-024'], criteria: null });
  assert.deepEqual(JSON.parse(calls[10].body), { reviewed: false });
  assert.deepEqual(JSON.parse(calls[11].body), { Тег: 'Инструкция' });
  assert.deepEqual(JSON.parse(calls[12].body), { url: 'https://org.test/api?token=t', group_id: 'DEV' });
  assert.deepEqual(JSON.parse(calls[13].body), { a: 'no', reason: 'r', by: 'Специалист КК' });
  assert.deepEqual(JSON.parse(calls[15].body), { llm_model: 'm' });
  assert.equal(api.audioUrl('call-024'), '/api/dialogs/call-024/audio');
  assert.equal(api.playerUrl('call-024'), '/api/dialogs/call-024/player');
});

test('checklist diff comes back as Markdown text and export is a plain link', async () => {
  const { calls, fetchFn } = recorder(200, '# Что изменится');
  const api = createApi('/api', fetchFn);
  assert.equal(await api.diffVersions(2, 3), '# Что изменится');
  assert.equal(await api.diffDraft({ version: 3 }), '# Что изменится');
  assert.deepEqual(calls.map(c => `${c.method} ${c.url}`), [
    'GET /api/checklist/diff?from=2&to=3&format=md', 'POST /api/checklist/diff?format=md',
  ]);
  assert.deepEqual(JSON.parse(calls[1].body), { version: 3 });
  assert.equal(api.exportUrl(3, 'csv'), '/api/checklist/export?v=3&format=csv');
});

test('a non-2xx answer throws with the server text', async () => {
  const { fetchFn } = recorder(422, '{"detail": "reason is required"}');
  await assert.rejects(createApi('/api', fetchFn).postDecision('a1', {}), /reason is required/);
});

test('X-CQA-User of the chosen employee goes with every request', async () => {
  const seen = [];
  const api = createApi('/api', async (url, init = {}) => { seen.push(init.headers); return new Response('{}'); }, () => ({ 'X-CQA-User': 'e1' }));
  await api.getState();
  await api.postDataset('DEV');
  assert.equal(seen[0]['X-CQA-User'], 'e1');
  assert.equal(seen[1]['X-CQA-User'], 'e1');
  assert.equal(seen[1]['Content-Type'], 'application/json');
});
