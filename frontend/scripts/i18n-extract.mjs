#!/usr/bin/env node
// Ключи перевода: все литералы t('...') из frontend/src и значения TERMS из terms.tsx (Term переводит их при отрисовке).
//   node frontend/scripts/i18n-extract.mjs                 → {"русский текст": ""} в stdout
//   node frontend/scripts/i18n-extract.mjs --check en.json → ключи, которых нет в словаре; код выхода 1, если такие есть
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const LIT = "'((?:[^'\\\\\\n]|\\\\.)*)'"; // одинарные кавычки, \' и другие экранирования внутри
const unescape = s => s.replace(/\\(.)/g, (m, c) => ({ n: '\n', t: '\t' })[c] ?? c);

const keys = new Set();
for (const f of readdirSync(SRC, { recursive: true })) {
  if (!/\.(tsx?|jsx?|mjs)$/.test(f)) continue;
  const code = readFileSync(join(SRC, f), 'utf8');
  for (const m of code.matchAll(new RegExp(`\\bt\\(\\s*${LIT}`, 'g'))) keys.add(unescape(m[1]));
  const terms = f === 'terms.tsx' && code.match(/export const TERMS = \{([\s\S]*?)\} as const/);
  if (terms) for (const m of terms[1].matchAll(new RegExp(`:\\s*${LIT}`, 'g'))) keys.add(unescape(m[1]));
}

const at = process.argv.indexOf('--check');
const dict = at > 0 ? JSON.parse(readFileSync(process.argv[at + 1], 'utf8')) : null;
const out = [...keys].filter(k => !dict || !dict[k]).sort();
process.stdout.write(`${JSON.stringify(Object.fromEntries(out.map(k => [k, ''])), null, 2)}\n`);
if (dict && out.length) process.exitCode = 1;
