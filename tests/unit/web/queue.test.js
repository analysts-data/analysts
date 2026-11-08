import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { byJev, groupOf, queueOrder, reasonOf, twoModels, syncNote } from '../../../web/js/queue.js';

const CL = {
  sections: ['Раздел'],
  criteria: [
    { id: 'b', sec: 0, name: 'Простой', type: 'bool', w: 10 },
    { id: 'r', sec: 0, name: 'Решение запроса', type: 'scale', w: 20, steps: [20, 15, 10, 5, 0], signal: 'resolution' },
    { id: 'f', sec: 0, name: 'Флаг', type: 'flag', w: 0, signal: 'risk', questions: [{ k: 'x', label: 'Нарушение' }] },
  ],
};
const clean = { b: { a: 'yes' }, r: { a: 20 }, f: { a: { x: false } } };
const dlg = (id, res = {}, extra = {}) => ({ id, res: { ...clean, ...res }, ...extra });

test('groupOf sorts dialogs into risk, review, next and other', () => {
  assert.equal(groupOf(dlg('1', { f: { a: { x: true } } }), CL, []), 'risk');
  assert.equal(groupOf(dlg('2', { b: { a: 'no', alt: 'yes' } }), CL, []), 'review');
  assert.equal(groupOf(dlg('3', { b: { a: 'yes', evFail: true } }), CL, []), 'review');
  assert.equal(groupOf(dlg('4', { r: { a: 5 } }), CL, []), 'next');
  assert.equal(groupOf(dlg('5'), CL, []), 'other');
});

test('a reviewed dialog with a flag drops out of risk', () => {
  assert.equal(groupOf(dlg('1', { f: { a: { x: true } } }, { reviewed: true }), CL, []), 'other');
});

test('a confirmed decision on the pair resolves the disagreement', () => {
  const d = dlg('2', { b: { a: 'no', alt: 'yes' } });
  const decided = [{ id: 'r1', kind: 'review', dlg: '2', cid: 'b', from: 'no', to: 'no', status: 'confirmed' }];
  assert.equal(groupOf(d, CL, decided), 'other');
  assert.equal(groupOf(d, CL, [{ ...decided[0], status: 'pending' }]), 'review');
});

test('any resolution answer below the top step has no clear next step, N/A and the top step do not', () => {
  assert.equal(groupOf(dlg('15', { r: { a: 15 } }), CL, []), 'next');
  assert.equal(groupOf(dlg('20', { r: { a: 20 } }), CL, []), 'other');
  assert.equal(groupOf(dlg('na', { r: { a: 'na' } }), CL, []), 'other');
  const lifted = [{ id: 'a1', kind: 'appeal', dlg: '15', cid: 'r', from: 15, to: 20, status: 'changed' }];
  assert.equal(groupOf(dlg('15', { r: { a: 15 } }), CL, lifted), 'other');
});

test('queueOrder puts groups in order and sorts by total inside, unscored first', () => {
  const ds = [
    dlg('t100'),
    dlg('t67', { b: { a: 'no' } }),
    dlg('risk', { f: { a: { x: true } } }),
    dlg('next', { r: { a: 15 } }),
    dlg('none', { b: { a: 'na' }, r: { a: 'na' } }),
  ];
  assert.deepEqual(queueOrder(ds, CL, []), ['risk', 'next', 'none', 't67', 't100']);
});

test('twoModels: second opinion is on, or the answers already carry one', () => {
  const off = { mode: { verifier: null }, dialogs: [dlg('1')] };
  assert.equal(twoModels(off), false);
  assert.equal(twoModels({ ...off, mode: { verifier: 'm2' } }), true);
  assert.equal(twoModels({ ...off, dialogs: [dlg('2', { b: { a: 'yes', alt: 'yes' } })] }), true);
});

test('reasonOf explains the prototype dialogs in words', () => {
  const state = JSON.parse(readFileSync(new URL('../../fixtures/state_prototype.json', import.meta.url), 'utf8'));
  const why = id => reasonOf(state.dialogs.find(d => d.id === id), state.checklist, state.appeals);
  assert.match(why('p1-ru-022').text, /Платная услуга/);
  assert.equal(why('p1-ru-022').cls, 'c-risk');
  assert.match(why('p1-en-008').text, /разошлись: 07/);
  assert.match(why('p1-kz-003').text, /06.*не найдена/);
  assert.match(why('p1-ru-003').text, /Корректная и полная консультация: 5 из 20/);
});

test('syncNote tells the group, the last sync and its error, never a link', () => {
  assert.equal(syncNote(null), '');
  assert.equal(syncNote({ group_id: 'DEV' }), 'Автосинхронизация DEV раз в 5 минут');
  const at = '2026-11-07T07:05:00+00:00';
  const time = new Date(at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  assert.equal(syncNote({ group_id: 'DEV', synced_at: at, added: 3, skipped: 62, error: null }),
    `Автосинхронизация DEV раз в 5 минут, последняя в ${time}: добавлено 3`);
  assert.equal(syncNote({ group_id: 'DEV', synced_at: at, added: 0, skipped: 0, error: 'набор DEV: API организаторов недоступен' }),
    `Автосинхронизация DEV раз в 5 минут, последняя в ${time}: ошибка — набор DEV: API организаторов недоступен`);
});

test('a low-confidence Jev-only answer goes to review and says Jev is unsure, not that a quote is missing', () => {
  const d = dlg('j', { b: { a: 'no', evFail: true, model: 'jev-latest', ev: [] } });
  assert.equal(groupOf(d, CL, []), 'review');
  assert.equal(reasonOf(d, CL, []).text, 'Jev не уверен в ответе: b');
  assert.equal(reasonOf(dlg('q', { b: { a: 'no', evFail: true, model: 'qwen3-6' } }), CL, []).text, 'Цитата для b не найдена в реплике');
  assert.equal(byJev({ model: 'jev-latest' }), true);
  assert.equal(byJev(undefined), false);
});
