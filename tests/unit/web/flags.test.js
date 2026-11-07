// Флаг после решения и обоснование по вопросам флага (web/js/scoring.js, web/js/format.js).
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { flagsOf, flagWhy } from '../../../web/js/scoring.js';
import { ansTxt } from '../../../web/js/format.js';

const fixtures = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures');
const checklist = JSON.parse(readFileSync(join(fixtures, 'checklist_v3.json'), 'utf8'));
const fc = checklist.criteria.find(c => c.type === 'flag');
const [q1, q2, q3] = fc.questions;
const on = (...ks) => Object.fromEntries(fc.questions.map(q => [q.k, ks.includes(q.k)]));
const dialog = (r) => ({ id: 'd1', res: { [fc.id]: r } });
const decision = (to, status = 'changed') => ({ dlg: 'd1', cid: fc.id, kind: 'appeal', from: on(q2.k), to, status });

test('flagsOf берёт флаг после последнего решения', () => {
  const d = dialog({ a: on(q2.k) });
  assert.deepEqual(flagsOf(d, checklist, []), [q2.label]);
  assert.deepEqual(flagsOf(d, checklist, [decision(on())]), []);
  assert.deepEqual(flagsOf(d, checklist, [decision(on(), 'pending')]), [q2.label]);
  assert.deepEqual(flagsOf(d, checklist, [decision(on()), decision(on(q1.k, q2.k))]), [q1.label, q2.label]);
});

test('ansTxt флага: найденные нарушения или «Нарушений нет»', () => {
  assert.equal(ansTxt(fc, on(q1.k, q3.k)), `${q1.label}, ${q3.label}`);
  assert.equal(ansTxt(fc, on()), 'Нарушений нет');
});

test('flagWhy делит обоснование по вопросам и берёт реплики каждого нарушения', () => {
  const why = `${q1.label}: Грубости нет; ${q2.label}: Предложил платно; без чека (реплики 6, 7); `
    + `${q3.label}: Счёт назван (реплики 9); Нарушение «${q3.label}» нашло только второе мнение, основная модель его не подтвердила.`;
  const fw = flagWhy(fc, { a: on(q2.k, q3.k), ev: [6, 7, 9], why });
  assert.deepEqual(fw.qs.map(x => [x.q.k, x.why, x.ev]), [
    [q1.k, 'Грубости нет', []],
    [q2.k, 'Предложил платно; без чека', [6, 7]],
    [q3.k, 'Счёт назван; Нарушение «' + q3.label + '» нашло только второе мнение, основная модель его не подтвердила.', [9]],
  ]);
  assert.equal(fw.rest, '');
  assert.deepEqual(fw.ev, []);
});

test('flagWhy без подписей вопросов: текст общий, реплики у единственного нарушения', () => {
  const fw = flagWhy(fc, { a: on(q2.k), ev: [6], why: 'Оператор предложил платную консультацию.' });
  assert.equal(fw.rest, 'Оператор предложил платную консультацию.');
  assert.deepEqual(fw.qs.find(x => x.q.k === q2.k).ev, [6]);
  assert.deepEqual(fw.ev, []);
});

test('flagWhy без подписей и с двумя нарушениями оставляет реплики общими', () => {
  const fw = flagWhy(fc, { a: on(q1.k, q2.k), ev: [3, 6], why: 'Два нарушения.' });
  assert.deepEqual(fw.qs.map(x => x.ev), [[], [], []]);
  assert.deepEqual(fw.ev, [3, 6]);
});
