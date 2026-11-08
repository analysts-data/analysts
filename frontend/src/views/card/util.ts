// Общие мелочи карточки: тон ответа, балл «7,5 / 15», склонение.
import { fn } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { ans, frac } from '../../lib/scoring.js';
import type { Tone } from '../../ui';

export function tone(c: any, a: any): Tone {
  if (a == null) return 'ev';
  if (a === 'na') return 'na';
  return frac(c, a) === 1 ? 'ok' : c.type === 'bool' ? 'risk' : 'ev';
}

export const ptsTxt = (c: any, a: any) => {
  const f = frac(c, a);
  return f == null ? '—' : `${fn(c.w * f)} / ${c.w}`;
};

export const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10,
    m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
};

export const scored = (cl: any) => cl.criteria.filter((c: any) => c.type !== 'flag');
export const lineBy = (d: any, n: number) => (d.lines || []).find((l: any) => !l.fold && l.n === n);
export const MANUAL = 'вручную'; // CriterionResult.model ручного ответа (src/cqa/services/answers.py)

/** Подсказка к итогу, в который не вошли критерии без ответа; null — итог полный или его нет. */
export function partialTip(d: any, cl: any, ap: any, total: number | null): string | null {
  if (total == null) return null;
  const ids = scored(cl)
    .filter((c: any) => ans(d, c.id, ap) == null)
    .map((c: any) => c.id);
  if (!ids.length) return null;
  return ids.length === 1 ? t('Итог без критерия {ids}: он ждёт оценки', { ids: ids[0] }) : t('Итог без критериев {ids}: они ждут оценки', { ids: ids.join(', ') });
}
