import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApi } from '../../../web/js/api.js';
import { canSave } from '../../../web/js/views/paste.js';

test('postPaste posts the contract body to /api/dialogs/text', async () => {
  const calls = [];
  const fetchFn = async (url, init = {}) => {
    calls.push({ method: init.method, url, body: init.body });
    return new Response('{"id": "paste-1"}', { status: 200 });
  };
  const body = { title: 'Демо для жюри', ch: 'chat', text: 'Клиент: привет\nОператор: здравствуйте' };
  const out = await createApi('/api', fetchFn).postPaste(body);
  assert.deepEqual(calls, [{ method: 'POST', url: '/api/dialogs/text', body: JSON.stringify(body) }]);
  assert.deepEqual(out, { id: 'paste-1' });
});

test('canSave requires both a title and dialog text', () => {
  assert.equal(canSave('Демо', 'Клиент: привет'), true);
  assert.equal(canSave('  ', 'Клиент: привет'), false);
  assert.equal(canSave('Демо', ' \n\t '), false);
});
