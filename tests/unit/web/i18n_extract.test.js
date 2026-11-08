import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONT = join(dirname(fileURLToPath(import.meta.url)), '../../../frontend');
const SCRIPT = join(FRONT, 'scripts/i18n-extract.mjs');

test('i18n-extract: t() literals with escaped quotes and TERMS values become keys; --check lists missing ones', () => {
  const root = mkdtempSync(join(tmpdir(), 'i18n-'));
  mkdirSync(join(root, 'scripts'));
  mkdirSync(join(root, 'src/views'), { recursive: true });
  copyFileSync(SCRIPT, join(root, 'scripts/i18n-extract.mjs'));
  writeFileSync(join(root, 'src/views/A.tsx'), "x = t('Оценено {done} из {total}', { done }); y = toast(t('Кнопка \\'Да\\'')); z = set('нет');");
  writeFileSync(join(root, 'src/terms.tsx'), "export const TERMS = {\n  na: 'Не применим',\n} as const;\nconst other = { k: 'не ключ' };");
  const script = join(root, 'scripts/i18n-extract.mjs');
  assert.deepEqual(JSON.parse(execFileSync('node', [script], { encoding: 'utf8' })), {
    "Кнопка 'Да'": '', 'Не применим': '', 'Оценено {done} из {total}': '',
  });
  const dict = join(root, 'en.json');
  writeFileSync(dict, JSON.stringify({ 'Не применим': 'Not applicable', "Кнопка 'Да'": '' }));
  const r = spawnSync('node', [script, '--check', dict], { encoding: 'utf8' });
  assert.equal(r.status, 1);
  assert.deepEqual(Object.keys(JSON.parse(r.stdout)), ["Кнопка 'Да'", 'Оценено {done} из {total}']);
});

test('i18n: t() keys in frontend/src are single-quoted literals, never templates or double quotes', () => {
  const bad = readdirSync(join(FRONT, 'src'), { recursive: true })
    .filter(f => /\.(tsx?|js)$/.test(f))
    .flatMap(f => readFileSync(join(FRONT, 'src', f), 'utf8').split('\n').filter(l => /\bt\(\s*[`"]/.test(l)).map(l => `${f}: ${l.trim()}`));
  assert.deepEqual(bad, []);
});
