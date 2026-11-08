import { test } from 'node:test';
import assert from 'node:assert/strict';
import { esc, titleOf, f2, fn, mmss, ansTxt } from '../../../frontend/src/lib/format.js';

const scale = { type: 'scale', steps: [20, 15, 10, 5, 0] };
const bool = { type: 'bool' };

test('esc escapes every HTML-significant character', () => {
  assert.equal(esc(`<b a="1">'&'</b>`), '&lt;b a=&quot;1&quot;&gt;&#39;&amp;&#39;&lt;/b&gt;');
  assert.equal(esc(null), '');
});

test('titleOf falls back to the dialog id', () => {
  assert.equal(titleOf({ id: 'p1', title: 'Звонок 024' }), 'Звонок 024');
  assert.equal(titleOf({ id: 'p1' }), 'p1');
});

test('numbers are formatted the Russian way', () => {
  assert.equal(f2(82.94), '82,94');
  assert.equal(f2(100), '100,00');
  assert.equal(f2(null), '—');
  assert.equal(fn(10.5), '10,5');
  assert.equal(fn(5.882352), '5,88');
  assert.equal(mmss(393), '06:33');
  assert.equal(mmss(4.1), '00:04');
});

test('ansTxt names every answer kind in Russian', () => {
  assert.equal(ansTxt(scale, null), 'ждёт оценки');
  assert.equal(ansTxt(scale, 'na'), 'N/A');
  assert.equal(ansTxt(bool, 'yes'), 'Да');
  assert.equal(ansTxt(bool, 'no'), 'Нет');
  assert.equal(ansTxt(scale, 15), '15 из 20');
});
