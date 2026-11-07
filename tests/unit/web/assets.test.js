import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL(`../../../${path}`, import.meta.url), 'utf8');
const html = read('web/index.html');
const css = read('web/styles.css');
const rootBlock = text => text.match(/:root\{[^}]*\}/)[0];

test('index.html and styles.css reference no external resources', () => {
  for (const text of [html, css]) {
    assert.doesNotMatch(text, /(src|href)\s*=\s*["']?\s*https?:/i);
    assert.doesNotMatch(text, /url\(\s*["']?\s*https?:/i);
  }
});

test('scripts and styles load by relative or root paths', () => {
  const paths = [...html.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)="([^"]+)"/g)].map(m => m[1]);
  assert.ok(paths.length >= 2);
  for (const p of paths) assert.match(p, /^\.?\//);
  assert.match(html, /<cqa-app\b/);
});

test('styles.css keeps the prototype :root tokens verbatim', () => {
  assert.equal(rootBlock(css), rootBlock(read('design/cqa-v3/index.html')));
});
