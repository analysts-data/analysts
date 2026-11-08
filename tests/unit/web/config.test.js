import { test } from 'node:test';
import assert from 'node:assert/strict';
import { configBody, modeText, providerBody, risks, whereOf } from '../../../web/js/config.js';

const CFG = { data_where: 'kz', anonymize: true, allow_real_data: false };
const FORM = { llm_provider: 'ds', verifier: '', evaluator: 'llm', anonymize: true, jev_api_key: ' j ', allow_real_data: false };

test('configBody maps the mode form to the PUT /api/config body', () => {
  assert.deepEqual(configBody(FORM), {
    llm_provider: 'ds', verifier: null, evaluator: 'llm', anonymize: true, jev_api_key: 'j', allow_real_data: false,
  });
  assert.equal(configBody({ ...FORM, verifier: 'jev' }).verifier, 'jev');
  assert.equal(configBody({ ...FORM, evaluator: 'jev' }).evaluator, 'jev');
  assert.equal(configBody({ ...FORM, verifier: 'env', anonymize: false }).anonymize, false);
});

test('providerBody trims the provider form and keeps an empty key empty', () => {
  const form = { id: 'ds', label: ' DeepSeek ', base_url: ' https://ds.test ', model: ' m ', profile: 'deepseek', where: 'external', key: ' ' };
  assert.deepEqual(providerBody(form), {
    label: 'DeepSeek', base_url: 'https://ds.test', model: 'm', profile: 'deepseek', where: 'external', key: '',
  });
});

test('whereOf finds where the chosen provider processes data', () => {
  const cfg = { providers: [{ id: 'env', where: 'kz' }, { id: 'loc', where: 'local' }] };
  assert.equal(whereOf(cfg, 'loc'), 'local');
  assert.equal(whereOf(cfg, 'nope'), undefined);
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
