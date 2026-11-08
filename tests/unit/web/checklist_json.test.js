// Импорт и экспорт чек-листа в формате вопросов Jev (web/js/checklist_json.js).
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { importQuestions, exportQuestions } from '../../../web/js/checklist_json.js';

const fixtures = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures');
const checklist = JSON.parse(readFileSync(join(fixtures, 'checklist_v3.json'), 'utf8'));
const empty = () => ({ version: 1, rules: '', sections: [], criteria: [] });

const noul = { type: 'noul', instructions: 'Оператор поздоровался', criteria: { true: 'Поздоровался', false: 'Не поздоровался' } };
const choice = { type: 'choice', instructions: 'Оператор назвал срок', criteria: { yes: 'Назвал', no: 'Не назвал', na: 'Срок не нужен' } };
const score = { type: 'score', instructions: 'Вежливость', min: 0, max: 10, criteria: ['10: Вежлив', '5: Частично', '0: Груб', 'n/a: Клиент молчал'] };

test('noul, choice и score становятся bool, bool с N/A и шкалой, исходный вопрос сохраняется в jev', () => {
  const { draft, added, updated } = importQuestions(empty(), { questions: { a: noul, b: choice, c: score } });
  assert.deepEqual([added, updated], [3, 0]);
  assert.deepEqual(draft.sections, ['Импортированные проверки']);
  const [a, b, c] = draft.criteria;
  assert.deepEqual(a, { id: 'a', name: 'a', type: 'bool', w: 0, na: false, naCond: null, text: noul.instructions, channel: 'all', sec: 0, jev: noul });
  assert.deepEqual([b.type, b.na, b.naCond, b.jev], ['bool', true, 'Срок не нужен', choice]);
  assert.deepEqual([c.type, c.steps, c.stepText, c.na, c.naCond], ['scale', [10, 5, 0], { 10: 'Вежлив', 5: 'Частично', 0: 'Груб' }, true, 'Клиент молчал']);
  assert.deepEqual(c.jev, score);
});

test('объект questions можно передать без обёртки', () => {
  assert.equal(importQuestions(empty(), { a: noul }).draft.criteria[0].id, 'a');
});

test('N/A принимается под ключами na и not_applicable, но не обоими сразу', () => {
  const alias = { ...choice, criteria: { yes: 'Да', no: 'Нет', not_applicable: 'Не к месту' } };
  assert.equal(importQuestions(empty(), { b: alias }).draft.criteria[0].naCond, 'Не к месту');
  for (const prefix of ['n/a', 'NA', 'not_applicable']) {
    const s = { ...score, criteria: ['10: Да', '0: Нет', `${prefix}: Молчал`] };
    assert.equal(importQuestions(empty(), { c: s }).draft.criteria[0].naCond, 'Молчал');
  }
  const both = { ...choice, criteria: { yes: 'Да', no: 'Нет', na: 'x', not_applicable: 'y' } };
  assert.throws(() => importQuestions(empty(), { b: both }), /только один ключ N\/A/);
  assert.throws(() => importQuestions(empty(), { a: { ...noul, criteria: { ...noul.criteria, na: 'x' } } }), /неподдерживаемые/);
});

test('ошибка в одном вопросе не меняет черновик', () => {
  const draft = structuredClone(checklist), before = structuredClone(draft);
  assert.throws(() => importQuestions(draft, { [checklist.criteria[0].id]: noul, bad: { type: 'score', instructions: 'x', criteria: ['10: Да'] } }), /^Error: bad:/);
  assert.throws(() => importQuestions(draft, {}), /непустой объект/);
  assert.deepEqual(draft, before);
});

test('обновление по ID меняет смысл и сохраняет раздел, название, вес, канал, сигнал и уточнение для звонка', () => {
  const draft = structuredClone(checklist);
  const old = draft.criteria.find(c => c.type === 'bool');
  Object.assign(old, { channel: 'chat', na: true, signal: 'risk', call: 'На звонке тоже' });
  const { draft: next, added, updated } = importQuestions(draft, { [old.id]: choice });
  assert.deepEqual([added, updated], [0, 1]);
  const c = next.criteria.find(x => x.id === old.id);
  assert.deepEqual([c.sec, c.name, c.w, c.channel, c.signal, c.call], [old.sec, old.name, old.w, 'chat', 'risk', 'На звонке тоже']);
  assert.deepEqual([c.text, c.naCond, c.jev], [choice.instructions, choice.criteria.na, choice]);
  assert.equal(next.criteria.length, draft.criteria.length);
});

test('критерий одного канала нельзя обновить вопросом без N/A', () => {
  for (const channel of ['chat', 'call']) {
    const draft = structuredClone(checklist);
    const old = draft.criteria.find(c => c.type === 'bool');
    Object.assign(old, { channel, na: true });
    assert.throws(() => importQuestions(draft, { [old.id]: noul }), /канал требует N\/A/);
  }
});

test('экспорт, импорт и снова экспорт дают тот же файл', () => {
  const draft = { ...structuredClone(checklist), criteria: checklist.criteria.filter(c => c.type !== 'flag') };
  const first = exportQuestions(draft);
  assert.deepEqual(Object.keys(first), draft.criteria.map(c => c.id));
  assert.deepEqual(exportQuestions(importQuestions(draft, first).draft), first);
  assert.deepEqual(exportQuestions(importQuestions(empty(), first).draft), first);
});

test('подвопросы флага экспортируются отдельными noul с ID «критерий_подвопрос»', () => {
  const flag = checklist.criteria.find(c => c.type === 'flag');
  const out = exportQuestions(checklist);
  for (const q of flag.questions) assert.equal(out[`${flag.id}_${q.k}`].type, 'noul');
  assert.equal(out[flag.id], undefined);
});
