import { test } from 'node:test';
import assert from 'node:assert/strict';
import { S } from '../../../frontend/src/lib/state.js';
import { createApi } from '../../../frontend/src/lib/api.js';
import { sent } from '../../../frontend/src/lib/telemetry.js';

test('successful appeal and decision requests become funnel events keyed by dialog and appeal id', async () => {
  S.features = ['telemetry'];
  const posted = [];
  globalThis.fetch = async (url, init) => {
    if (url.endsWith('/telemetry')) posted.push(...JSON.parse(init.body));
    return new Response('{}', { status: 200 });
  };
  const ok = async () => new Response('{}', { status: 200 });
  const failed = async () => new Response('{"detail": "нет"}', { status: 409 });
  await createApi('/api', ok, () => ({}), sent).postAppeal({ dlg: 'sc-19', cid: '04', ask: 20, ev: [], comment: 'x', by: 'Оператор' });
  await createApi('/api', ok, () => ({}), sent).postDecision(12, { to: 20, reason: 'x', reviewer: 'Проверяющий' });
  await createApi('/api', ok, () => ({}), sent).get('/appeals/stats');
  await createApi('/api', failed, () => ({}), sent).postAppeal({ dlg: 'sc-20' }).catch(() => {});
  const { flush } = await import('../../../frontend/src/lib/telemetry.js');
  flush();
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(posted.map(e => [e.event, e.props]), [
    ['appeal_submit', { id: 'sc-19' }],
    ['decision_submit', { id: '12' }],
  ]);
});
