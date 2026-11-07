import { test } from 'node:test';
import assert from 'node:assert/strict';
import { allowed, signOf } from '../../../web/js/appeal_form.js';

test('allowed answers follow the criterion type and its N/A permission', () => {
  assert.deepEqual(allowed({ type: 'bool', na: false }), ['yes', 'no']);
  assert.deepEqual(allowed({ type: 'bool', na: true }), ['yes', 'no', 'na']);
  assert.deepEqual(allowed({ type: 'scale', na: false, steps: [10, 7, 4, 0] }), [10, 7, 4, 0]);
  assert.deepEqual(allowed({ type: 'scale', na: true, steps: [20, 15, 10, 5, 0] }), [20, 15, 10, 5, 0, 'na']);
});

test('signOf gives the role signature sent as by and reviewer', () => {
  assert.equal(signOf('qa'), 'Специалист КК');
  assert.equal(signOf('operator'), 'Оператор');
  assert.equal(signOf('reviewer'), 'Проверяющий');
});
