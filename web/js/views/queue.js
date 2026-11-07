// Экран очереди: группы приоритета, плитки-фильтры из хеша, поиск и панель оценки. DOM-модуль.
import * as state from '../state.js';
import { groupOf, queueOrder, reasonOf } from '../queue.js';
import { calc, flagsOf, r2, frac, ans } from '../scoring.js';
import { esc, titleOf, f2, fn, ansTxt } from '../format.js';
import { href } from '../router.js';

const { S } = state;

const GROUPS = [
  ['risk', 'Грубые ошибки', 'c-risk', 'флаг ставит любая из двух моделей, итог он не обнуляет'],
  ['review', 'Нужна проверка человека', 'c-info', 'модели разошлись или цитата не нашлась в реплике'],
  ['next', 'Без понятного следующего шага', 'c-ev', 'критерий с сигналом «Решение запроса» на нижних ступенях'],
  ['other', 'Остальные', 'c-na', ''],
];

// Видимые строки в порядке очереди: фильтры из параметров хеша, поиск в S.
function rowsOf() {
  const p = S.r?.params || {};
  const cl = S.checklist, ap = S.appeals;
  const ql = S.q.trim().toLowerCase();
  const lost = p.lost ? cl.criteria.find(c => c.id === p.lost) : null;
  return S.dialogs
    .map(d => ({ d, c: calc(d, cl, ap), g: groupOf(d, cl, ap) }))
    .filter(({ d, g }) => {
      if (p.grp && p.grp !== g) return false;
      if (p.lang && d.lang !== p.lang) return false;
      if (p.ch && d.ch !== p.ch) return false;
      if (lost) { const f = frac(lost, ans(d, lost.id, ap)); if (f == null || f >= 1) return false; }
      if (ql) {
        const text = (titleOf(d) + ' ' + (d.lines || []).map(l => l.text || '').join(' ')).toLowerCase();
        if (!text.includes(ql)) return false;
      }
      return true;
    });
}

const hasFilters = () => !!(S.r?.params && (S.r.params.grp || S.r.params.lang || S.r.params.ch || S.r.params.lost) || S.q);

export function view() {
  const p = S.r?.params || {};
  const all = S.dialogs.map(d => ({ d, c: calc(d, S.checklist, S.appeals), g: groupOf(d, S.checklist, S.appeals) }));
  const cnt = k => all.filter(x => x.g === k).length;
  const totals = all.map(x => x.c.total).filter(x => x != null);
  const avg = totals.length ? r2(totals.reduce((a, b) => a + b, 0) / totals.length) : null;
  const pa = S.appeals.filter(a => a.status === 'pending').length;
  const rows = rowsOf();
  if (rows.length && !rows.some(x => x.d.id === S.qsel)) S.qsel = rows[0].d.id;
  const byId = Object.fromEntries(rows.map(x => [x.d.id, x]));
  const seq = queueOrder(S.dialogs, S.checklist, S.appeals).map(id => byId[id]).filter(Boolean);
  const tile = (g, title, n, note) => `<button type="button" class="tile" data-act="grp" data-g="${g}" aria-pressed="${p.grp === g}"><span class="t">${title}</span><strong>${n}</strong><span class="muted small">${note}</span></button>`;
  const sel = (id, label, cur, vals) => `<label class="small muted" for="${id}">${label}</label><select id="${id}" class="fld" data-act="${id}">${vals.map(([v, t]) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`;
  const lost = c => c.losses.slice(0, 3).map(r => `${r.c.id} ${esc(ansTxt(r.c, r.a))}`).join(', ');
  let body = '';
  for (const [g, title, cls, hint] of GROUPS) {
    const rs = seq.filter(x => x.g === g);
    if (!rs.length) continue;
    body += `<tbody><tr class="grp"><td colspan="6"><span class="chip ${cls}">${title}: ${rs.length}</span> <span class="muted" style="font-weight:400;margin-left:8px">${hint}</span></td></tr>`;
    body += rs.map(x => {
      const why = reasonOf(x.d, S.checklist, S.appeals);
      return `<tr class="click${x.d.id === S.qsel ? ' sel' : ''}" data-act="open" data-id="${esc(x.d.id)}">
      <td><a href="${href('d', x.d.id)}" style="font-weight:600;text-decoration:none">${esc(titleOf(x.d))}</a></td>
      <td>${x.d.ch === 'call' ? 'Звонок' : 'Чат'}, ${x.d.lang}</td>
      <td class="num" style="font-weight:700">${f2(x.c.total)}</td>
      <td>${why.text ? `<span class="chip ${why.cls}">${esc(why.text)}</span>` : ''}</td>
      <td class="muted small">${lost(x.c) || '—'}</td>
      <td>${statusOf(x.d, x.c)}</td></tr>`;
    }).join('') + '</tbody>';
  }
  const run = S.run, running = run && run.status === 'running';
  return `
  <div class="head"><div><h1 class="h1">Диалоги</h1><p class="sub">Сначала разговоры с нарушениями и спорными ответами модели</p></div>
    <div class="row only-qa">
      <label class="sr" for="gid">Набор по group_id</label><input id="gid" class="fld" value="DEV" style="width:110px">
      <button type="button" class="btn" data-act="load">Получить набор</button>
      <label class="btn" for="jsonf">Загрузить JSON</label><input id="jsonf" type="file" accept="application/json" class="sr" data-act="jsonf">
    </div></div>
  <section class="card pad row only-qa" aria-label="Оценка набора">
    ${running ? `<div style="flex:1 1 320px" class="stack"><div class="row" style="justify-content:space-between"><span><b>Оценка: ${run.done} из ${run.total}</b></span><span class="muted small">${fn(run.cost || 0)} $, осталось ~${Math.ceil(run.eta_s || 0)} с${run.errors?.length ? `, ошибок: ${run.errors.length}` : ''}</span></div>
      <div class="runbar"><i style="width:${run.total ? Math.round(100 * run.done / run.total) : 0}%"></i></div></div>
      <button type="button" class="btn" data-act="stop">Остановить</button>`
    : `<div style="flex:1 1 320px">Оценка набора по чек-листу v${S.checklist.version}: грубые ошибки и споры поднимутся наверх очереди.</div>
      <button type="button" class="btn pri" data-act="run">Оценить</button>`}
  </section>
  <section class="tiles" aria-label="Быстрые фильтры">
    ${tile('risk', 'Грубые ошибки', cnt('risk'), `ещё ${S.dialogs.filter(d => d.reviewed && flagsOf(d, S.checklist).length).length} проверено`)}
    ${tile('review', 'Нужна проверка', cnt('review'), 'модели разошлись или цитата не найдена')}
    ${tile('next', 'Без следующего шага', cnt('next'), 'клиент не знает, что делать дальше')}
    <a class="tile" href="${href('appeals')}"><span class="t">Апелляции</span><strong>${pa}</strong><span class="muted small">ждут решения проверяющего</span></a>
    <a class="tile" href="${href('analytics')}"><span class="t">Средний итог</span><strong>${f2(avg)}</strong><span class="muted small">по ${totals.length} диалогам, открыть аналитику</span></a>
  </section>
  <section class="card" aria-label="Список диалогов">
    <div class="row" style="padding:12px 14px;border-bottom:1px solid var(--line)">
      <label class="sr" for="q">Поиск</label><input id="q" class="fld" style="flex:1 1 220px" placeholder="Номер диалога или текст реплики" value="${esc(S.q)}">
      ${sel('fl', 'Язык', p.lang || '', [['', 'Все'], ['RU', 'RU'], ['KZ', 'KZ'], ['EN', 'EN']])}
      ${sel('fc', 'Канал', p.ch || '', [['', 'Все'], ['chat', 'Чат'], ['call', 'Звонок']])}
      ${hasFilters() ? `<button type="button" class="btn sm" data-act="clear">Сбросить фильтры</button>` : ''}
    </div>
    <div class="tablewrap"><table style="min-width:860px">
      <thead><tr><th>Диалог</th><th>Канал и язык</th><th class="num">Итог</th><th>Почему в очереди</th><th>Где потеряны баллы</th><th>Статус</th></tr></thead>
      ${body || `<tbody><tr><td colspan="6" class="empty">По этим фильтрам диалогов нет. Сбросьте фильтры, чтобы увидеть весь набор.</td></tr></tbody>`}
    </table></div>
  </section>
  <p class="muted xs">Клавиши J и K перемещаются по списку, Enter открывает карточку. Числа и реплики учебные.</p>`;
}

function statusOf(d, c) {
  if (c.pending) return '<span class="chip c-ev">Ждёт оценки</span>';
  if (S.appeals.some(a => a.dlg === d.id && a.status === 'pending')) return '<span class="chip c-info">Апелляция</span>';
  return d.reviewed ? '<span class="chip c-ok">Проверен</span>' : '<span class="chip c-na">Не проверен</span>';
}

const go = h => { if (location.hash === h) state.render(); else location.hash = h; };
const setParam = (k, v) => { const n = { ...S.r.params }; if (v) n[k] = v; else delete n[k]; return href('queue', null, n); };

export const actions = {
  grp: t => go(setParam('grp', S.r.params.grp === t.dataset.g ? '' : t.dataset.g)),
  clear: () => { S.q = ''; go(href('queue')); },
  open: (t, e) => { if (e.target.closest('a')) return; location.hash = href('d', t.dataset.id); },
  fl: t => go(setParam('lang', t.value)),
  fc: t => go(setParam('ch', t.value)),
  load: () => state.postDataset?.(document.getElementById('gid')?.value || ''),
  jsonf: t => { const f = t.files?.[0]; if (f) state.uploadDataset?.(f); },
  run: () => state.startRun?.({ dialogs: hasFilters() ? rowsOf().map(x => x.d.id) : null, criteria: null }),
  stop: () => { if (S.run?.id != null) state.api?.cancelRun(S.run.id); },
};

// Живой поиск без смены хеша.
document.addEventListener('input', e => {
  if (e.target.id !== 'q') return;
  S.q = e.target.value;
  state.render();
});

// J и K — курсор по очереди и соседний диалог в карточке, Enter — открыть выделенный.
document.addEventListener('keydown', e => {
  if (e.target.closest('input,textarea,select,dialog') || e.metaKey || e.ctrlKey || e.altKey) return;
  const down = e.key === 'j' || e.key === 'о', up = e.key === 'k' || e.key === 'л';
  if (!down && !up && e.key !== 'Enter') return;
  const r = S.r;
  if (!r || !S.checklist || !S.dialogs?.length) return;
  if (r.page === 'd') {
    if (down || up) {
      const ord = queueOrder(S.dialogs, S.checklist, S.appeals), i = ord.indexOf(r.id);
      const n = ord[i + (down ? 1 : -1)];
      if (n) location.hash = href('d', n);
    }
    return;
  }
  if (r.page !== 'queue') return;
  const ids = rowsOf().map(x => x.d.id);
  if (!ids.length) return;
  if (down || up) {
    const i = ids.indexOf(S.qsel);
    const n = ids[Math.min(ids.length - 1, Math.max(0, (i < 0 ? 0 : i) + (down ? 1 : -1)))];
    if (n !== S.qsel) { S.qsel = n; state.render(); }
  } else if (S.qsel && ids.includes(S.qsel)) location.hash = href('d', S.qsel);
});
