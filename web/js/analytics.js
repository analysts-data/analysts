// Чистые функции аналитики (analytics-coaching, design.md решение 2). Без DOM и fetch.
// Ответы берутся через ans/frac из scoring.js, чтобы доля аналитики не разошлась с итогом карточки.
import { ans, frac, r2, flagsOf, calc } from './scoring.js';
import { groupOf } from './queue.js';

// Виды грубых ошибок (signal=risk) через flagsOf: счётчики по подвопросам, диалоги с флагом и проверенные из них.
// {flaggedIds: [..], reviewed: n, kinds: [{k, label, n}]}
export function flagStats(S) {
  const questions = S.checklist.criteria
    .filter(c => c.type === 'flag')
    .flatMap(c => c.questions || []);
  const labels = new Map(S.dialogs.map(d => [d.id, flagsOf(d, S.checklist)]));
  const flaggedIds = S.dialogs.filter(d => labels.get(d.id).length).map(d => d.id);
  return {
    flaggedIds,
    reviewed: flaggedIds.filter(id => S.dialogs.find(d => d.id === id).reviewed).length,
    kinds: questions.map(q => ({
      k: q.k,
      label: q.label,
      n: flaggedIds.filter(id => labels.get(id).includes(q.label)).length,
    })),
  };
}

// Качество самой оценки: согласие моделей, проваленные основания, ждущие решения пары
// и исходы решений с разбивкой по kind. byCriterion — решённые пары критерий×язык,
// где модель расходится с людьми: сортировка по убыванию changed.
export function qualityStats(S) {
  let answers = 0, disagree = 0, evFail = 0;
  const awaitingPairs = [];
  const decided = S.appeals.filter(a => a.status === 'confirmed' || a.status === 'changed');
  const hasDecision = (dlg, cid) => decided.some(a => a.dlg === dlg && a.cid === cid);
  for (const d of S.dialogs) {
    for (const c of S.checklist.criteria) {
      if (c.type === 'flag') continue;
      const r = d.res[c.id];
      if (!r) continue;
      answers++;
      if (r.alt != null && r.alt !== r.a) disagree++;
      if (r.evFail) evFail++;
      if ((r.alt != null && r.alt !== r.a) || r.evFail) {
        if (!hasDecision(d.id, c.id)) awaitingPairs.push(`${d.id}/${c.id}`);
      }
    }
  }
  const byStatus = (kind, statuses) =>
    Object.fromEntries(statuses.map(st => [st, S.appeals.filter(a => a.kind === kind && a.status === st).length]));
  const langOf = id => S.dialogs.find(d => d.id === id).lang;
  const pairs = new Map();
  for (const a of decided) {
    const key = `${a.cid}|${langOf(a.dlg)}`;
    const p = pairs.get(key) || { cid: a.cid, lang: langOf(a.dlg), decided: 0, changed: 0 };
    p.decided++;
    if (a.status === 'changed') p.changed++;
    pairs.set(key, p);
  }
  return {
    answers,
    agree: answers - disagree,
    evFail,
    awaiting: awaitingPairs.length,
    reviews: byStatus('review', ['confirmed', 'changed']),
    appeals: byStatus('appeal', ['pending', 'confirmed', 'changed', 'closed']),
    byCriterion: [...pairs.values()].sort((a, b) => b.changed - a.changed),
  };
}

// Повторяющиеся причины снижения: группы по точному значению tag на сниженных применимых ответах
// (доля < 1 по ans). «Не назначено» — записи в owners нет.
// {recurring: [{tag, dialogs: [id], criteria: [cid], langs: [..], owner}], single: n}
export function reasonsStats(S) {
  const groups = new Map();
  for (const d of S.dialogs) {
    for (const c of S.checklist.criteria) {
      if (c.type === 'flag') continue;
      const r = d.res[c.id];
      if (!r || !r.tag) continue;
      const f = frac(c, ans(d, c.id, S.appeals));
      if (f == null || f >= 1) continue;
      const g = groups.get(r.tag) || { tag: r.tag, dialogs: [], criteria: [], langs: [] };
      if (!g.dialogs.includes(d.id)) g.dialogs.push(d.id);
      if (!g.criteria.includes(c.id)) g.criteria.push(c.id);
      if (!g.langs.includes(d.lang)) g.langs.push(d.lang);
      groups.set(r.tag, g);
    }
  }
  const rows = [...groups.values()].map(g => ({
    ...g,
    langs: [...g.langs].sort((a, b) => (LANGS.indexOf(a) + 1 || 99) - (LANGS.indexOf(b) + 1 || 99)),
    owner: (S.owners || {})[g.tag] ?? 'Не назначено',
  }));
  rows.sort((a, b) => b.dialogs.length - a.dialogs.length);
  return {
    recurring: rows.filter(g => g.dialogs.length >= 2),
    single: rows.filter(g => g.dialogs.length === 1).length,
  };
}

// Выгрузка итогов по диалогам (задача 2.5): страховка на случай сверки чисел контрольного набора
// с эталоном жюри. Итог — из calc с учётом решений, ответы — через ans.
export function resultsCsv(dialogs, checklist, appeals) {
  const cols = checklist.criteria.filter(c => c.type !== 'flag');
  const cell = a => (a == null ? 'ждёт оценки' : a === 'na' ? '—' : String(a));
  const lines = [
    ['Диалог', 'Канал', 'Язык', 'Итог', 'Грубые ошибки', ...cols.map(c => c.id)].join(';'),
    ...dialogs.map(d =>
      csvRow([
        d.id,
        d.ch,
        d.lang,
        calc(d, checklist, appeals).total ?? '—',
        flagsOf(d, checklist).join(', '),
        ...cols.map(c => cell(ans(d, c.id, appeals))),
      ])
    ),
  ];
  return `\uFEFF${lines.join('\n')}`;
}

// Плитка «Без следующего шага»: диалоги группы next по groupOf из queue.js —
// столько же строк покажет очередь по ссылке #/queue?grp=next.
export const nextStepStats = S => ({
  dialogIds: S.dialogs.filter(d => groupOf(d, S.checklist, S.appeals) === 'next').map(d => d.id),
});

// Выгрузка повторяющихся причин: BOM, разделитель «;» (задача 3.2, кнопка «Скачать CSV»).
export function reasonsCsv(S) {
  const lines = [
    ['Причина', 'Разговоров', 'Критерии', 'Языки', 'Что менять', 'Диалоги'].join(';'),
    ...reasonsStats(S).recurring.map(g =>
      csvRow([g.tag, g.dialogs.length, g.criteria.join(','), g.langs.join(','), g.owner, g.dialogs.join(', ')])
    ),
  ];
  return `\uFEFF${lines.join('\n')}`;
}

const LANGS = ['RU', 'KZ', 'EN'];

// Строка CSV: поле с «;», кавычкой или переводом строки — в кавычках (RFC 4180), остальные как есть.
const csvRow = fields =>
  fields.map(v => (/[;"\n\r]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(';');

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
