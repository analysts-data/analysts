import { test } from 'node:test';
import assert from 'node:assert/strict';
import { configBody, presetOf, risks } from '../../../web/js/config.js';

const CFG = { data_where: 'kz', anonymize: true, allow_real_data: false };
const FIELDS = { llm_base_url: ' https://kz.test/v1 ', llm_model: ' qwen ', llm_profile: 'plain', llm_api_key: '', jev: false, jev_api_key: '', allow_real_data: false };

test('presetOf names the mode of a config', () => {
  assert.equal(presetOf({ data_where: 'local', anonymize: false }), 'local');
  assert.equal(presetOf({ data_where: 'kz', anonymize: true }), 'anon');
  assert.equal(presetOf({ data_where: 'external', anonymize: false }), 'raw');
});

test('configBody maps a preset and the form to the PUT /api/config body', () => {
  assert.deepEqual(configBody('local', 'external', FIELDS), {
    llm_base_url: 'https://kz.test/v1', llm_model: 'qwen', llm_profile: 'plain', llm_api_key: '',
    data_where: 'local', anonymize: false, verifier: null, jev_api_key: '', allow_real_data: false,
  });
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
