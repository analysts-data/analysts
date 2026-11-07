// Чистые функции аналитики (analytics-coaching, design.md решение 2). Без DOM и fetch.
// Ответы берутся через ans/frac из scoring.js, чтобы доля аналитики не разошлась с итогом карточки.
import { ans, frac, r2 } from './scoring.js';

const LANGS = ['RU', 'KZ', 'EN'];

// Счётчики одного набора ответов: n — применимые, na — «не применим», pend — записи в res нет.
function tally(S, c, dialogs = S.dialogs) {
  let n = 0, na = 0, pend = 0, lost = 0, sum = 0, yes = 0;
  for (const d of dialogs) {
    const a = ans(d, c.id, S.appeals);
    if (a == null) { pend++; continue; }
    if (a === 'na') { na++; continue; }
    const f = frac(c, a);
    if (f == null) continue;
    n++;
    if (c.type === 'scale') sum += a;
    if (a === 'yes') yes++;
    if (f < 1) lost++;
  }
  return { n, na, pend, lost, sum, yes };
}

// [{cid, name, w, type, n, na, pend, lost, share, val, byLang: [{lang, n, lost}]}]
// val: scale — средняя ступень, bool — процент «Да»; только не-флаговые критерии.
export function criteriaStats(S) {
  return S.checklist.criteria
    .filter(c => c.type !== 'flag')
    .map(c => {
      const t = tally(S, c);
      const langs = [...new Set(S.dialogs.map(d => d.lang))].sort(
        (a, b) => (LANGS.indexOf(a) + 1 || 99) - (LANGS.indexOf(b) + 1 || 99)
      );
      return {
        cid: c.id,
        name: c.name,
        w: c.w,
        type: c.type,
        n: t.n,
        na: t.na,
        pend: t.pend,
        lost: t.lost,
        share: t.n ? t.lost / t.n : null,
        // шкала — средняя ступень из максимума (15.56 из 20), Да/Нет — процент «Да»
        val: t.n ? (c.type === 'scale' ? r2(t.sum / t.n) : r2((100 * t.yes) / t.n)) : null,
        byLang: langs
          .map(lang => ({ lang, ...tally(S, c, S.dialogs.filter(d => d.lang === lang)) }))
          .filter(l => l.n),
      };
    });
}
