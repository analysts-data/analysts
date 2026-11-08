import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { r2, frac, ans, calc, flagsOf } from '../../../frontend/src/lib/scoring.js';

const fixture = name => new URL(`../../fixtures/${name}`, import.meta.url);
const state = JSON.parse(readFileSync(fixture('state_prototype.json'), 'utf8'));
const CL = state.checklist;
const byId = id => state.dialogs.find(d => d.id === id);
const crit = id => CL.criteria.find(c => c.id === id);
const dialogOf = answers => ({ id: 'x', res: Object.fromEntries(Object.entries(answers).map(([k, a]) => [k, { a }])) });

test('r2 rounds half up after removing binary noise', () => {
  assert.equal(r2(82.935), 82.94);
  assert.equal(r2(77.685), 77.69);
  assert.equal(r2(1.005), 1.01);
  assert.equal(r2(0.285), 0.29);
  assert.equal(r2((100 * 2.3) / 80), 2.88);
  assert.equal(r2((100 * 1.15) / 8), 14.38);
});

test('frac covers yes, no, scale step, na, missing answer and flag', () => {
  assert.equal(frac(crit('01'), 'yes'), 1);
  assert.equal(frac(crit('01'), 'no'), 0);
  assert.equal(frac(crit('04'), 15), 0.75);
  assert.equal(frac(crit('04'), 'na'), null);
  assert.equal(frac(crit('04'), null), null);
  assert.equal(frac(crit('08'), { insult: true }), null);
});

test('ans applies only the last confirmed or changed decision of the pair', () => {
  const d = dialogOf({ '04': 15, '05': 'no', '06': 7 });
  d.id = 'd1';
  const appeals = [
    { id: 'a1', kind: 'appeal', dlg: 'd1', cid: '05', from: 'no', ask: 'yes', to: 'no', status: 'confirmed' },
    { id: 'a2', kind: 'review', dlg: 'd1', cid: '04', from: 15, to: 20, status: 'changed' },
    { id: 'a3', kind: 'appeal', dlg: 'd1', cid: '06', from: 7, ask: 10, to: null, status: 'closed' },
    { id: 'a4', kind: 'appeal', dlg: 'd2', cid: '06', from: 7, ask: 10, to: 10, status: 'changed' },
  ];
  assert.equal(ans(d, '05', appeals), 'no');
  assert.equal(ans(d, '04', appeals), 20);
  assert.equal(ans(d, '06', appeals), 7);
  assert.equal(ans(d, '01', appeals), null);
  assert.equal(calc(d, CL, appeals).total, calc(dialogOf({ '04': 20, '05': 'no', '06': 7 }), CL, []).total);
});

test('calc gives the prototype anchors 77.69 and 82.94', () => {
  const ex = dialogOf({ '01': 'yes', '02': 'na', '03': 'na', '04': 15, '05': 'yes', '06': 7, '07': 'no' });
  assert.equal(calc(ex, CL, []).total, 77.69);
  assert.equal(calc(byId('call-024'), CL, state.appeals).total, 82.94);
});

const vectorsFile = fixture('scoring_vectors.json');
test('calc passes every shared scoring vector', { skip: !existsSync(vectorsFile) }, () => {
  for (const v of JSON.parse(readFileSync(vectorsFile, 'utf8'))) {
    const cl = typeof v.checklist === 'string' ? CL : v.checklist;
    assert.equal(calc(dialogOf(v.answers), cl, []).total, v.total, v.name);
  }
});

test('calc returns null total when nothing applicable has weight', () => {
  const c = calc(dialogOf({ '02': 'na', '03': 'na', '04': 'na', '07': 'na' }), CL, []);
  assert.equal(c.total, null);
});

test('call-024 losses are sorted, tie keeps checklist order, and sum to 100 - total', () => {
  const c = calc(byId('call-024'), CL, state.appeals);
  assert.deepEqual(c.losses.map(r => r.c.id), ['04', '07', '06']);
  assert.equal(r2(c.losses[0].loss), 5.88);
  assert.equal(r2(c.losses[1].loss), 5.88);
  assert.equal(r2(c.losses[2].loss), 5.29);
  const sum = c.losses.reduce((s, r) => s + r.loss, 0);
  assert.ok(Math.abs(sum - 17.06) < 0.01);
  assert.ok(Math.abs(sum - (100 - c.total)) < 0.01);
  assert.equal(c.secs.reduce((s, x) => s + x.w, 0), c.W);
});

test('pending counts criteria without a result and leaves them out of the total', () => {
  const full = byId('call-024');
  const d = { ...full, res: { ...full.res } };
  delete d.res['04'];
  const c = calc(d, CL, []);
  assert.equal(c.pending, 1);
  assert.equal(ans(d, '04', []), null);
  assert.equal(c.W, calc(full, CL, []).W - 20);
});

test('override replaces one answer for the decision preview', () => {
  assert.equal(calc(byId('call-024'), CL, [], { cid: '04', val: 20 }).total, 88.82);
});

test('flags change flagsOf but never the total', () => {
  const base = byId('call-024');
  const on = { ...base, res: { ...base.res, '08': { a: { insult: false, paid: true, leak: false } } } };
  assert.equal(calc(on, CL, []).total, calc(base, CL, []).total);
  assert.deepEqual(flagsOf(on, CL, []), [crit('08').questions.find(q => q.k === 'paid').label]);
  assert.deepEqual(flagsOf(base, CL, []), []);
});
