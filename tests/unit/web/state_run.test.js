import { test } from 'node:test';
import assert from 'node:assert/strict';
import { S, cancelRun, init, startRun } from '../../../web/js/state.js';

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
