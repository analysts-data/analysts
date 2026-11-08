import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Собранный web/ (make web) и исходники frontend/: без внешних ссылок, <cqa-app>, расчёт итога дословно.
const read = path => readFileSync(new URL(`../../../${path}`, import.meta.url), 'utf8');
const html = read('web/index.html');
const css = read('web/assets/index.css');
const rootBlock = text => text.match(/:root\{[^}]*\}/)[0];

test('built index.html and css reference no external resources', () => {
  for (const text of [html, css]) {
    assert.doesNotMatch(text, /(src|href)\s*=\s*["']?\s*https?:/i);
    assert.doesNotMatch(text, /url\(\s*["']?\s*https?:/i);
  }
});

test('scripts and styles load by relative paths into <cqa-app>', () => {
  const paths = [...html.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)="([^"]+)"/g)].map(m => m[1]);
  assert.ok(paths.length >= 2);
  for (const p of paths) assert.match(p, /^\.\//);
  assert.match(html, /<cqa-app\b/);
});

test('web/js/scoring.js is frontend/src/lib/scoring.js verbatim (defence imports it in the page)', () => {
  assert.equal(read('web/js/scoring.js'), read('frontend/src/lib/scoring.js'));
});

test('frontend tokens keep the prototype :root verbatim', () => {
  assert.equal(rootBlock(read('frontend/src/index.css')), rootBlock(read('design/cqa-v3/index.html')));
});
