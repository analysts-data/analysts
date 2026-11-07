// Числа посчитаны вручную по фикстуре analytics_state.json (design analytics-coaching, решение 7).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { coachingStats, goodExamples } from '../../../web/js/analytics.js';

const S = JSON.parse(readFileSync(new URL('../../fixtures/analytics_state.json', import.meta.url), 'utf8'));

test('coachingStats gives 10 moments over 6 criteria, biggest group first', () => {
  const { groups } = coachingStats(S);
  assert.deepEqual(groups.map(g => [g.cid, g.items.length]), [['04', 4], ['07', 2], ['02', 1], ['03', 1], ['05', 1], ['06', 1]]);
  assert.equal(groups.flatMap(g => g.items).length, 10);
  assert.ok(!groups[0].items.some(x => x.dialogId === 'p1-en-006'), 'a3 raised p1-en-006/04 to full score');
});

test('a moment carries the operator line, why and better', () => {
  const m = coachingStats(S).groups[0].items.find(x => x.dialogId === 'call-024');
  assert.equal(m.key, 'call-024/04');
  assert.equal(m.lang, 'RU');
  assert.equal(m.answer, 15);
  assert.equal(m.line.who, 'operator');
  assert.equal(m.line.text, 'Я передам вопрос специалистам.');
  assert.match(m.why, /срок ответа/);
  assert.match(m.better, /двух рабочих дней/);
});

test('goodExamples takes operator evidence lines with full score', () => {
  assert.equal(goodExamples(S, '01', 10).length, 4);
  assert.equal(goodExamples(S, '01').length, 3);
  assert.deepEqual(Object.keys(goodExamples(S, '01')[0]).sort(), ['dialogId', 'lineNo', 'text']);
  assert.deepEqual(goodExamples(S, '04'), []);
});
