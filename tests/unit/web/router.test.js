import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseHash, href } from '../../../frontend/src/lib/router.js';

test('parseHash splits page, id and query params', () => {
  assert.deepEqual(parseHash(''), { page: 'queue', id: null, params: {} });
  assert.deepEqual(parseHash('#/queue'), { page: 'queue', id: null, params: {} });
  assert.deepEqual(parseHash('#/d/p1-ru-003'), { page: 'd', id: 'p1-ru-003', params: {} });
  assert.deepEqual(parseHash('#/appeals/a1'), { page: 'appeals', id: 'a1', params: {} });
  assert.deepEqual(parseHash('#/checklist'), { page: 'checklist', id: null, params: {} });
  assert.deepEqual(parseHash('#/queue?lost=07&lang=KZ'), { page: 'queue', id: null, params: { lost: '07', lang: 'KZ' } });
});

test('unknown route falls back to the queue', () => {
  assert.deepEqual(parseHash('#/nope'), { page: 'queue', id: null, params: {} });
});

test('href builds hashes that parseHash reads back', () => {
  assert.equal(href('d', 'p1-ru-003'), '#/d/p1-ru-003');
  assert.equal(href('queue', null, { grp: 'risk' }), '#/queue?grp=risk');
  assert.equal(href('queue', null, { grp: '', lang: 'KZ' }), '#/queue?lang=KZ');
  assert.deepEqual(parseHash(href('d', 'a b/c')), { page: 'd', id: 'a b/c', params: {} });
});
