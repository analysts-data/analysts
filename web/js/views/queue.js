// Очередь, группа 3: набор и запуск оценки. Группа 4 дорисует группы, плитки, фильтры и строки.
import { fn } from '../format.js';
import { groupOf, queueOrder } from '../queue.js';
import { S, startRun } from '../state.js';

// Видимые строки в порядке очереди; без фильтров — null, сервер берёт весь набор.
function visible() {
  const p = S.r.params;
  if (!p.grp && !p.lang && !p.ch) return null;
  return queueOrder(S.dialogs, S.checklist, S.appeals).filter(id => {
    const d = S.dialogs.find(x => x.id === id);
    return (!p.ch || d.ch === p.ch) && (!p.lang || d.lang === p.lang) && (!p.grp || groupOf(d, S.checklist, S.appeals) === p.grp);
  });
}

function runPanel(run) {
  if (!run) return '<button type="button" class="btn pri" data-act="run">Оценить</button>';
  const pct = run.total ? (100 * run.done) / run.total : 0;
  const state = run.status === 'running' ? '' : run.status === 'cancelled' ? 'Оценка остановлена. ' : 'Оценка завершена. ';
  const eta = run.eta_s != null && run.status === 'running' ? `, осталось около ${Math.ceil(run.eta_s)} с` : '';
  return `<div style="flex:1 1 320px" class="stack"><div class="row" style="justify-content:space-between">
      <span id="runProgress">${state}<b>${run.done}/${run.total}</b> диалогов</span>
      <span class="muted small">${run.calls} вызовов, $${fn(run.cost)}${eta}${run.errors.length ? `, ошибок: ${run.errors.length}` : ''}</span></div>
    <div class="runbar"><i style="width:${pct}%"></i></div></div>
    ${run.status === 'running' ? '<button type="button" class="btn" data-act="stop">Остановить</button>' : '<button type="button" class="btn pri" data-act="run">Оценить</button>'}`;
}

export function view(S) {
  return `
  <div class="head"><div><h1 class="h1">Диалоги</h1><p class="sub">Сначала разговоры с нарушениями и спорными ответами модели</p></div>
    <div class="row only-qa">
      <label class="sr" for="gid">Набор по group_id</label><input id="gid" class="fld" value="DEV" style="width:110px">
      <button type="button" class="btn" data-act="load">Получить набор</button>
      <label class="btn" for="jsonf">Загрузить JSON</label><input id="jsonf" type="file" accept="application/json" class="sr" data-act="jsonf">
    </div></div>
  <section class="card pad row only-qa" aria-label="Оценка набора">${runPanel(S.run)}</section>`;
}

export const actions = {
  run: () => startRun({ dialogs: visible(), criteria: null }),
};
