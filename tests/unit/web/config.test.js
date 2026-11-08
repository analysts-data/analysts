import { test } from 'node:test';
import assert from 'node:assert/strict';
import { configBody, modeText, presetOf, risks } from '../../../frontend/src/lib/config.js';

const CFG = { data_where: 'kz', anonymize: true, allow_real_data: false };
const FIELDS = { llm_base_url: ' https://kz.test/v1 ', llm_model: ' qwen ', llm_profile: 'plain', llm_api_key: '', evaluator: 'llm', jev: false, jev_api_key: '', allow_real_data: false };

test('presetOf names the mode of a config', () => {
  assert.equal(presetOf({ data_where: 'local', anonymize: false }), 'local');
  assert.equal(presetOf({ data_where: 'kz', anonymize: true }), 'anon');
  assert.equal(presetOf({ data_where: 'external', anonymize: false }), 'raw');
});

test('configBody maps a preset and the form to the PUT /api/config body', () => {
  assert.deepEqual(configBody('local', 'external', FIELDS), {
    llm_base_url: 'https://kz.test/v1', llm_model: 'qwen', llm_profile: 'plain', llm_api_key: '',
    data_where: 'local', anonymize: false, verifier: null, evaluator: 'llm', jev_api_key: '', allow_real_data: false,
  });
  assert.equal(configBody('anon', 'kz', { ...FIELDS, evaluator: 'jev' }).evaluator, 'jev');
  const anon = configBody('anon', 'kz', { ...FIELDS, jev: true, jev_api_key: ' j ' });
  assert.deepEqual([anon.data_where, anon.anonymize, anon.verifier, anon.jev_api_key], ['kz', true, 'jev', 'j']);
  assert.equal(configBody('raw', 'external', FIELDS).anonymize, false);
});

test('risks asks to confirm raw text abroad and real calls, but not a local model', () => {
  assert.deepEqual(risks(CFG, { data_where: 'kz', anonymize: true, allow_real_data: false }), []);
  assert.equal(risks(CFG, { data_where: 'external', anonymize: false, allow_real_data: false }).length, 1);
  assert.equal(risks(CFG, { data_where: 'local', anonymize: false, allow_real_data: false }).length, 0);
  assert.equal(risks(CFG, { data_where: 'kz', anonymize: true, allow_real_data: true }).length, 1);
  assert.deepEqual(risks({ ...CFG, allow_real_data: true }, { data_where: 'kz', anonymize: true, allow_real_data: true }), []);
});

test('modeText tells recorded answers from a live model', () => {
  const m = { where: 'kz', anonymized: true, model: 'qwen3-6', verifier: null };
  assert.equal(modeText(m, 'replay'), 'Обработка: Казахстан · транскрипты обезличены · Записанные ответы');
  assert.equal(modeText(m, 'live'), 'Обработка: Казахстан · транскрипты обезличены · модель qwen3-6');
  assert.equal(modeText({ ...m, where: 'local', anonymized: false, verifier: 'jev' }, 'record'),
    'Обработка: локально · без обезличивания · модель qwen3-6 · второе мнение: jev');
});
