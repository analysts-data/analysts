import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const state = JSON.parse(readFileSync(new URL('../../fixtures/state_prototype.json', import.meta.url), 'utf8'));

test('state fixture has exactly the GET /api/state keys', () => {
  assert.deepEqual(Object.keys(state).sort(), ['appeals', 'checklist', 'dialogs', 'mode', 'owners', 'versions']);
  assert.deepEqual(Object.keys(state.mode).sort(), ['anonymized', 'model', 'verifier', 'where']);
  assert.deepEqual(state.versions.map(v => v.v), [1, 2, 3]);
});

test('state fixture holds the ten prototype dialogs, call lines start at t = s', () => {
  assert.equal(state.dialogs.length, 10);
  const call = state.dialogs.find(d => d.ch === 'call');
  for (const l of call.lines.filter(l => !l.fold)) {
    assert.equal(l.t, l.s);
    assert.equal('e' in l, false);
  }
  assert.equal(state.dialogs.filter(d => !d.cost).length, 1);
  assert.equal(state.appeals.find(a => a.id === 'a2').status, 'closed');
});
