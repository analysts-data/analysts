import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { existsSync } from 'node:fs';
import { criteriaStats } from '../../../web/js/analytics.js';

// Числа в этом файле посчитаны вручную по данным прототипа (design.md, решение 7):
// ans учитывает решения (апелляция a3 меняет 04 у p1-en-006 с 15 на 20), запись r1 закрывает
// расхождение call-024/04. Числа зафиксированы, а не вычисляются в тестах.
const state = existsSync(new URL('../../fixtures/analytics_state.json', import.meta.url))
  ? JSON.parse(readFileSync(new URL('../../fixtures/analytics_state.json', import.meta.url), 'utf8'))
  : null;

test('fixture: 10 dialogs, 70 non-flag res entries, 4 appeals by status and 1 review', () => {
  assert.ok(state, 'tests/fixtures/analytics_state.json missing');
  assert.equal(state.dialogs.length, 10);
  const nonFlag = state.checklist.criteria.filter(c => c.type !== 'flag');
  assert.equal(nonFlag.length, 7);
  assert.equal(
    state.dialogs.reduce((s, d) => s + nonFlag.filter(c => d.res[c.id]).length, 0),
    70
  );
  const statuses = {};
  for (const a of state.appeals.filter(a => a.kind === 'appeal')) statuses[a.status] = (statuses[a.status] || 0) + 1;
  assert.deepEqual(statuses, { pending: 1, confirmed: 1, changed: 1, closed: 1 });
  const reviews = state.appeals.filter(a => a.kind === 'review');
  assert.equal(reviews.length, 1);
  assert.equal(reviews[0].id, 'r1');
  assert.equal(reviews[0].dlg, 'call-024');
  assert.equal(reviews[0].cid, '04');
  assert.equal(reviews[0].status, 'confirmed');
});

const row = rows => cid => rows.find(r => r.cid === cid);

test('criteriaStats: resolution criterion 04 counts answers via ans, appeal a3 lifts p1-en-006 to full', () => {
  const r04 = row(criteriaStats(state))('04');
  assert.deepEqual(
    { n: r04.n, na: r04.na, pend: r04.pend, lost: r04.lost },
    { n: 9, na: 1, pend: 0, lost: 5 }
  );
  assert.equal(r04.share, 5 / 9);
  assert.ok(Math.abs(r04.val - 15.56) < 0.01);
});

test('criteriaStats: bool criterion 03 shows percent of yes', () => {
  const r03 = row(criteriaStats(state))('03');
  assert.deepEqual(
    { n: r03.n, na: r03.na, lost: r03.lost },
    { n: 8, na: 2, lost: 2 }
  );
  assert.equal(r03.val, 75);
});

test('criteriaStats: byLang cells of 07 are lost of applicable by language', () => {
  const r07 = row(criteriaStats(state))('07');
  assert.deepEqual(
    r07.byLang.map(l => `${l.lost} из ${l.n}`),
    ['3 из 5', '1 из 2', '1 из 2']
  );
});

test('criteriaStats: flag criterion is not a row, missing res entry counts as pend', () => {
  const rows = criteriaStats(state);
  assert.equal(rows.find(r => r.type === 'flag'), undefined);
  const cut = JSON.parse(JSON.stringify(state));
  delete cut.dialogs[0].res['04'];
  const r04 = row(criteriaStats(cut))('04');
  assert.deepEqual(
    { n: r04.n, na: r04.na, pend: r04.pend },
    { n: 8, na: 1, pend: 1 }
  );
});
