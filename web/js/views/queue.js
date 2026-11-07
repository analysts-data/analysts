// Экран очереди: группы приоритета, плитки-фильтры из хеша, поиск и панель оценки. DOM-модуль.
import { S, startRun, cancelRun, postDataset, uploadDataset, saveSource, render } from '../state.js';
import { groupOf, queueOrder, reasonOf, syncNote } from '../queue.js';
import { calc, flagsOf, r2, frac, ans } from '../scoring.js';
import { esc, titleOf, f2, fn, ansTxt } from '../format.js';
import { href, parseHash } from '../router.js';

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

// Порядок видимых строк — как на экране: группы и итог из queueOrder.
function visibleOrder() {
  const byId = Object.fromEntries(rowsOf().map(x => [x.d.id, x]));
  return queueOrder(S.dialogs, S.checklist, S.appeals).map(id => byId[id]).filter(Boolean);
}

const hasFilters = () => !!(S.r?.params && (S.r.params.grp || S.r.params.lang || S.r.params.ch || S.r.params.lost) || S.q);

// Идентификаторы видимых строк в порядке очереди; без фильтров — null, сервер берёт весь набор.
const visible = () => (hasFilters() ? visibleOrder().map(x => x.d.id) : null);

// Без запуска — сводка набора, как в прототипе: оценённые диалоги и стоимость из Dialog.cost как есть.
function idlePanel(all) {
  const done = all.filter(x => !x.c.pending).length, n = all.length;
  const calls = S.dialogs.reduce((s, d) => s + (d.cost ? d.cost.calls + d.cost.verifier_calls : 0), 0);
  const usd = S.dialogs.reduce((s, d) => s + (d.cost ? d.cost.usd : 0), 0);
  return `<div style="flex:1 1 320px" class="stack"><div class="row" style="justify-content:space-between">
      <span><b>${done} из ${n}</b> оценено по чек-листу v${S.checklist.version}</span><span class="muted small">${calls} вызовов, $${fn(usd)}</span></div>
    <div class="runbar"><i style="width:${n ? (100 * done) / n : 0}%"></i></div></div>
    <button type="button" class="btn pri" data-act="run">Оценить</button>`;
}

function runPanel(run, all) {
  if (!run) return idlePanel(all);
  const pct = run.total ? (100 * run.done) / run.total : 0;
  const state = run.status === 'running' ? '' : run.status === 'cancelled' ? 'Оценка остановлена. ' : 'Оценка завершена. ';
  const eta = run.eta_s != null && run.status === 'running' ? `, осталось около ${Math.ceil(run.eta_s)} с` : '';
  return `<div style="flex:1 1 320px" class="stack"><div class="row" style="justify-content:space-between">
      <span id="runProgress">${state}оценено <b>${run.done} из ${run.total}</b> ответов по критериям</span>
      <span class="muted small">${run.calls} вызовов, $${fn(run.cost)}${eta}${run.errors.length ? `, ошибок: ${run.errors.length}` : ''}</span></div>
    <div class="runbar"><i style="width:${pct}%"></i></div></div>
    ${run.status === 'running' ? '<button type="button" class="btn" data-act="stop">Остановить</button>' : '<button type="button" class="btn pri" data-act="run">Оценить</button>'}`;
}

export function view() {
  const p = S.r?.params || {};
  const all = S.dialogs.map(d => ({ d, c: calc(d, S.checklist, S.appeals), g: groupOf(d, S.checklist, S.appeals) }));
  const cnt = k => all.filter(x => x.g === k).length;
  const totals = all.map(x => x.c.total).filter(x => x != null);
  const avg = totals.length ? r2(totals.reduce((a, b) => a + b, 0) / totals.length) : null;
  const pa = S.appeals.filter(a => a.status === 'pending').length;
  const seq = visibleOrder();
  const ids = seq.map(x => x.d.id);
  if (ids.length && !ids.includes(S.qsel)) S.qsel = ids[0];
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
  return `
  <div class="head"><div><h1 class="h1">Диалоги</h1><p class="sub">Сначала разговоры с нарушениями и спорными ответами модели</p></div>
    <div class="row only-qa">
      <label class="sr" for="gid">Набор по group_id</label><input id="gid" class="fld" value="DEV" style="width:110px">
      <label class="sr" for="orgurl">Ссылка API организаторов</label><input id="orgurl" type="url" class="fld" placeholder="Ссылка API организаторов (необязательно)" autocomplete="off" style="width:240px">
      <button type="button" class="btn" data-act="load">Получить набор</button>
      <label class="btn" for="jsonf">Загрузить JSON</label><input id="jsonf" type="file" accept="application/json" class="sr" data-act="jsonf">
    </div></div>
  ${S.source ? `<p class="muted small only-qa">${esc(syncNote(S.source))}</p>` : ''}
  <section class="card pad row only-qa" aria-label="Оценка набора">${runPanel(S.run, all)}</section>
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
  <p class="muted xs">Клавиши J и K перемещаются по списку, Enter открывает карточку.</p>`;
}

function statusOf(d, c) {
  if (c.pending) return '<span class="chip c-ev">Ждёт оценки</span>';
  if (S.appeals.some(a => a.dlg === d.id && a.status === 'pending')) return '<span class="chip c-info">Апелляция</span>';
  return d.reviewed ? '<span class="chip c-ok">Проверен</span>' : '<span class="chip c-na">Не проверен</span>';
}

const go = h => { if (location.hash === h) render(); else location.hash = h; };
const setParam = (k, v) => { const n = { ...S.r.params }; if (v) n[k] = v; else delete n[k]; return href('queue', null, n); };

export const actions = {
  grp: t => go(setParam('grp', S.r.params.grp === t.dataset.g ? '' : t.dataset.g)),
  clear: () => { S.q = ''; go(href('queue')); },
  open: (t, e) => { if (e.target.closest('a')) return; location.hash = href('d', t.dataset.id); },
  fl: t => go(setParam('lang', t.value)),
  fc: t => go(setParam('ch', t.value)),
  load: () => {
    const gid = document.getElementById('gid')?.value || '';
    const url = document.getElementById('orgurl')?.value.trim();
    return url ? saveSource(url, gid) : postDataset(gid); // ссылка сохраняется на сервере и включает автосинхронизацию
  },
  jsonf: t => { const f = t.files?.[0]; if (f) uploadDataset(f); },
  run: () => startRun({ dialogs: visible(), criteria: null }),
  stop: () => cancelRun(),
};

// Живой поиск без смены хеша.
document.addEventListener('input', e => {
  if (e.target.id !== 'q') return;
  S.q = e.target.value;
  render();
});

// J и K — курсор по очереди и соседний диалог в карточке, Enter — открыть выделенный.
document.addEventListener('keydown', e => {
  if (e.target.closest('input,textarea,select,dialog') || e.metaKey || e.ctrlKey || e.altKey) return;
  const down = e.key === 'j' || e.key === 'о', up = e.key === 'k' || e.key === 'л';
  if (!down && !up && e.key !== 'Enter') return;
  if (!S.checklist || !S.dialogs?.length) return;
  // Хеш читаем напрямую: быстрый повтор до события hashchange не должен смотреть прошлый маршрут.
  const { page, id } = parseHash(location.hash);
  if (page === 'd') {
    if (down || up) {
      const ord = queueOrder(S.dialogs, S.checklist, S.appeals), i = ord.indexOf(id);
      const n = ord[i + (down ? 1 : -1)];
      if (n) location.hash = href('d', n);
    }
    return;
  }
  if (page !== 'queue') return;
  const ids = visibleOrder().map(x => x.d.id);
  if (!ids.length) return;
  if (down || up) {
    const i = ids.indexOf(S.qsel);
    const n = ids[Math.min(ids.length - 1, Math.max(0, (i < 0 ? 0 : i) + (down ? 1 : -1)))];
    if (n !== S.qsel) { S.qsel = n; render(); }
  } else if (S.qsel && ids.includes(S.qsel)) location.hash = href('d', S.qsel);
});
