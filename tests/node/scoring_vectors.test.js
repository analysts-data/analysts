// Общие векторы итога читают pytest (tests/unit/test_fixtures.py) и node --test.
// Число векторов здесь и там совпадает: EXPECTED_VECTORS один и тот же.
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const fixtures = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures');
const vectors = JSON.parse(readFileSync(join(fixtures, 'scoring_vectors.json'), 'utf8'));
const checklistV3 = JSON.parse(readFileSync(join(fixtures, 'checklist_v3.json'), 'utf8'));
const EXPECTED_VECTORS = 7;

const resolveChecklist = ref => (typeof ref === 'string' ? checklistV3 : ref);

test('векторы совпадают по числу с прогоном pytest', () => {
  assert.equal(vectors.length, EXPECTED_VECTORS);
});

test('у каждого вектора поля name, checklist, answers, total', () => {
  for (const v of vectors) {
    assert.deepEqual(Object.keys(v).sort(), ['answers', 'checklist', 'name', 'total'], v.name);
    const ids = new Set(resolveChecklist(v.checklist).criteria.map(c => c.id));
    for (const cid of Object.keys(v.answers)) assert.ok(ids.has(cid), `${v.name}: критерий ${cid}`);
    assert.ok(v.total === null || typeof v.total === 'number', v.name);
  }
});

test('якоря прототипа на месте: 77,69 и 82,94', () => {
  const totals = new Map(vectors.map(v => [v.name, v.total]));
  assert.equal(totals.get('пример из чек-листа: 77,69'), 77.69);
  assert.equal(totals.get('звонок 024: 82,94'), 82.94);
});
