import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { existsSync } from 'node:fs';
import {
  criteriaStats,
  flagStats,
  qualityStats,
  reasonsStats,
  resultsCsv,
  nextStepStats,
  reasonsCsv,
} from '../../../frontend/src/lib/analytics.js';

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

test('flagStats: kinds 1/1/2 via flagsOf, 4 flagged dialogs, 1 of them reviewed', () => {
  const f = flagStats(state);
  assert.deepEqual(
    f.kinds.map(k => `${k.k}:${k.n}`),
    ['insult:1', 'paid:1', 'leak:2']
  );
  assert.equal(f.flaggedIds.length, 4);
  assert.deepEqual(
    f.flaggedIds.sort(),
    ['p1-kz-015', 'p1-ru-009', 'p1-ru-022', 'p1-ru-029'].sort()
  );
  assert.equal(f.reviewed, 1);
});

test('qualityStats: answers, agreements, evFail and awaiting review pairs', () => {
  const q = qualityStats(state);
  assert.deepEqual(
    { answers: q.answers, agree: q.agree, evFail: q.evFail, awaiting: q.awaiting },
    { answers: 70, agree: 68, evFail: 1, awaiting: 2 }
  );
  // ждут решения — расхождение или проваленное основание без записи confirmed|changed:
  // call-024/04 закрыт проверкой r1, остаются p1-en-008/07 и p1-kz-003/06
});

test('qualityStats: outcomes of reviews and appeals by status', () => {
  const q = qualityStats(state);
  assert.deepEqual(q.reviews, { confirmed: 1, changed: 0 });
  assert.deepEqual(q.appeals, { pending: 1, confirmed: 1, changed: 1, closed: 1 });
});

test('qualityStats: byCriterion rows only for decided pairs, sorted by changed desc', () => {
  const q = qualityStats(state);
  assert.ok(q.byCriterion.every(r => r.decided >= 1));
  assert.equal(q.byCriterion.reduce((s, r) => s + r.decided, 0), 3);
  assert.equal(q.byCriterion.reduce((s, r) => s + r.changed, 0), 1);
  const changed = q.byCriterion.map(r => r.changed);
  assert.deepEqual(changed, [...changed].sort((a, b) => b - a));
  assert.deepEqual(q.byCriterion[0], { cid: '04', lang: 'EN', decided: 1, changed: 1 });
});

test('reasonsStats: recurring tags with owners, top group of 5 dialogs, 6 single tags', () => {
  const r = reasonsStats(state);
  assert.equal(r.recurring.length, 4);
  assert.equal(r.single, 6);
  assert.equal(r.recurring[0].tag, 'Нет итога и прощания');
  assert.deepEqual(
    r.recurring[0].dialogs.sort(),
    ['call-024', 'p1-en-008', 'p1-kz-015', 'p1-ru-003', 'p1-ru-022'].sort()
  );
  const srok = r.recurring.find(x => x.tag === 'Не назван срок ответа');
  // p1-en-006 не в группе: апелляция a3 подняла ответ 04 до полного балла
  assert.deepEqual(srok.dialogs.sort(), ['call-024', 'p1-kz-003', 'p1-ru-009'].sort());
  assert.equal(srok.owner, 'Инструкция');
  assert.deepEqual(r.recurring[0].criteria, ['07']);
  assert.deepEqual(r.recurring[0].langs, ['RU', 'KZ', 'EN']);
  // группы по убыванию числа диалогов
  const sizes = r.recurring.map(x => x.dialogs.length);
  assert.deepEqual(sizes, [...sizes].sort((a, b) => b - a));
});

test('reasonsStats: owner is "Не назначено" when owners has no record for the tag', () => {
  // сценарий спецификации на «Грубом тоне»: в фикстуре прототипа он одиночный,
  // поэтому адресат проверяем на минимальном состоянии без записи в owners
  const one = answers => ({
    checklist: state.checklist,
    appeals: [],
    owners: {},
    dialogs: [
      { id: 'd1', lang: 'RU', res: { '05': { a: 'no', tag: 'Грубый тон' } } },
      { id: 'd2', lang: 'RU', res: { '05': { a: 'no', tag: 'Грубый тон' } } },
    ],
  });
  const r = reasonsStats(one());
  assert.equal(r.recurring.length, 1);
  assert.equal(r.recurring[0].tag, 'Грубый тон');
  assert.equal(r.recurring[0].owner, 'Не назначено');
  assert.equal(r.single, 0);
});

test('nextStepStats: dialogs of queue group next via groupOf, the handoff at 15 of 20 included', () => {
  assert.deepEqual(nextStepStats(state), { dialogIds: ['call-024', 'p1-ru-003'] });
});

test('reasonsCsv: BOM, header and 4 recurring reason rows', () => {
  const csv = reasonsCsv(state);
  assert.ok(csv.startsWith('\uFEFF'));
  const lines = csv.slice(1).split('\n');
  assert.equal(lines.length, 5);
  assert.equal(lines[0], 'Причина;Разговоров;Критерии;Языки;Что менять;Диалоги');
  assert.equal(
    lines[1],
    'Нет итога и прощания;5;07;RU,KZ,EN;Инструкция;call-024, p1-ru-022, p1-ru-003, p1-kz-015, p1-en-008'
  );
  assert.equal(lines[2], 'Не назван срок ответа;3;04;RU,KZ;Инструкция;call-024, p1-ru-009, p1-kz-003');
});

test('resultsCsv: BOM, header with criterion columns and one row per dialog', () => {
  const csv = resultsCsv(state.dialogs, state.checklist, state.appeals);
  assert.ok(csv.startsWith('\uFEFF'));
  const lines = csv.slice(1).split('\n');
  assert.equal(lines[0], 'Диалог;Канал;Язык;Итог;Грубые ошибки;01;02;03;04;05;06;07');
  assert.equal(lines.length, 11);
  assert.equal(lines[1], 'call-024;call;RU;82.94;;yes;—;yes;15;yes;7;no');
  // итог p1-en-006 — 100 после решения a3, грубые ошибки — подписи flagsOf
  assert.equal(lines[10], 'p1-en-006;chat;EN;100;;yes;yes;yes;20;yes;10;yes');
  assert.equal(
    lines[2],
    'p1-ru-022;chat;RU;81.25;Платная услуга в обход компании;yes;yes;—;10;yes;10;no'
  );
  assert.equal(lines[7], 'p1-ru-029;chat;RU;76;Оскорбление клиента;yes;yes;yes;20;no;4;yes');
});

test('resultsCsv: «—» for N/A and total, «ждёт оценки» without record', () => {
  const cut = JSON.parse(JSON.stringify(state));
  cut.dialogs = [cut.dialogs.find(d => d.id === 'p1-ru-025')];
  let csv = resultsCsv(cut.dialogs, cut.checklist, cut.appeals);
  assert.equal(csv.slice(1).split('\n')[1], 'p1-ru-025;chat;RU;100;;yes;yes;—;—;yes;10;—');
  cut.dialogs[0].res = {};
  csv = resultsCsv(cut.dialogs, cut.checklist, cut.appeals);
  assert.equal(
    csv.slice(1).split('\n')[1],
    'p1-ru-025;chat;RU;—;;' + ['01', '02', '03', '04', '05', '06', '07'].map(() => 'ждёт оценки').join(';')
  );
});

test('reasonsCsv quotes a reason with the separator so columns stay in place', () => {
  const S = {
    checklist: { criteria: [{ id: '01', type: 'bool', w: 10, na: false }] },
    dialogs: ['d1', 'd2'].map(id => ({ id, lang: 'RU', res: { '01': { a: 'no', tag: 'Срок; канал "чат"' } } })),
    appeals: [],
    owners: {},
  };
  const row = reasonsCsv(S).split('\n')[1];
  assert.equal(row, '"Срок; канал ""чат""";2;01;RU;Не назначено;d1, d2');
});
