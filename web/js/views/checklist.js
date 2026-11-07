// Редактор чек-листа: черновик — копия применяемой версии, правки живут в браузере до сохранения.
import { S, api, reload, render, startRun, toast } from '../state.js';
import { esc, fn } from '../format.js';

const SIGNALS = [['', 'Нет'], ['resolution', 'Решение запроса'], ['risk', 'Риск']];
const TYPES = [['bool', 'Да / Нет'], ['scale', 'Шкала'], ['flag', 'Флаг нарушения, без баллов']];
const TYPE_NAME = { bool: 'Да/Нет', scale: 'Шкала', flag: 'Флаг' };
const CHANNELS = [['all', 'Все каналы'], ['chat', 'Чат'], ['call', 'Звонок']];

const scored = cl => cl.criteria.filter(c => c.type !== 'flag');
const wsum = cs => cs.reduce((s, x) => s + (Number(x.w) || 0), 0);
const opts = (list, cur) => list.map(([v, t]) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${esc(t)}</option>`).join('');
const selected = () => S.draft.criteria.find(x => x.id === S.cSel);
// pending приходит только из ответа PUT /api/checklist и держится, пока у диалогов нет записи критерия
const waiting = () => (S.pending || []).filter(cid => S.dialogs.some(d => !d.res[cid]));

export function view(S) {
  // новая версия с сервера сбрасывает черновик; если сохранение упало, правки остаются
  if (S.draft?.version !== S.checklist.version) S.draft = structuredClone(S.checklist);
  const cl = S.checklist, dr = S.draft, pend = waiting(), run = S.run?.status === 'running' ? S.run : null;
  const c = selected() || dr.criteria[0];
  S.cSel = c?.id;
  const sum = wsum(scored(dr));
  const dirty = JSON.stringify(dr) !== JSON.stringify(cl);
  const changed = id => {
    const o = cl.criteria.find(x => x.id === id), n = dr.criteria.find(x => x.id === id);
    return !o || JSON.stringify(o) !== JSON.stringify(n);
  };
  return `
  <div class="head"><div><h1 class="h1">Чек-лист качества</h1><p class="sub">Версия ${cl.version} применяется к набору. Изменения сохраняются новой версией.</p></div>
    <div class="row only-qa">${dirty ? '<span class="chip c-ev">Есть несохранённые изменения</span>' : ''}
      <button type="button" class="btn" data-act="creset" ${dirty ? '' : 'disabled'}>Отменить изменения</button>
      <button type="button" class="btn pri" data-act="csave" ${dirty && !S.busy ? '' : 'disabled'}>Сохранить как v${cl.version + 1}</button></div></div>
  ${pend.length || run ? `<section class="card pad row" style="justify-content:space-between;background:var(--ev-soft);border-color:var(--ev-line)">
    <span>${pend.length ? `Критерии ${pend.map(esc).join(', ')} ждут оценки: <b>${pend.length * S.dialogs.length} вызовов</b> основной модели, остальные ответы берутся из кэша.` : ''}
      ${run ? `Оценено <b>${run.done}/${run.total}</b>, $${fn(run.cost)}${run.eta_s != null ? `, осталось около ${Math.ceil(run.eta_s)} с` : ''}.` : ''}</span>
    <span class="row only-qa">${run ? '<button type="button" class="btn" data-act="stop">Остановить</button>' : ''}
      ${pend.length ? `<button type="button" class="btn pri" data-act="crun" ${run || S.busy ? 'disabled' : ''}>${run ? 'Идёт оценка…' : 'Оценить набор'}</button>` : ''}</span></section>` : ''}
  <div class="split" style="grid-template-columns:minmax(0,.9fr) minmax(0,1.3fr)">
    <section class="card" style="padding:10px" aria-label="Структура чек-листа">
      ${dr.sections.map((s, si) => `<p class="label row" style="justify-content:space-between;padding:8px 10px 4px"><span>${esc(s)}</span><span>${wsum(scored(dr).filter(x => x.sec === si)) || ''}</span></p><div class="clist">
        ${dr.criteria.filter(x => x.sec === si).map(x => `<button type="button" class="citem" data-act="csel" data-cid="${esc(x.id)}" aria-current="${x.id === S.cSel}"><span class="muted small">${esc(x.id)}</span><span>${esc(x.name)}${changed(x.id) ? ' <span class="chip c-ev">изменён</span>' : ''}${pend.includes(x.id) ? ' <span class="chip c-ev">ждёт оценки</span>' : ''}${x.signal ? ` <span class="chip c-info">${esc(SIGNALS.find(s => s[0] === x.signal)?.[1] ?? x.signal)}</span>` : ''}</span><span class="muted xs">${TYPE_NAME[x.type] ?? esc(x.type)}${x.na ? ', N/A' : ''}</span><b class="num">${x.type === 'flag' ? '—' : esc(x.w)}</b></button>`).join('')}</div>`).join('')}
      <div class="row" style="padding:12px 10px 4px;border-top:1px solid var(--line2);margin-top:8px">
        <span class="chip ${sum === 100 ? 'c-ok' : 'c-ev'}">Сумма весов ${sum}</span>${sum !== 100 ? '<span class="muted xs">Итог всё равно приводится к 100</span>' : ''}
        <button type="button" class="btn sm only-qa" data-act="cadd" style="margin-left:auto">Добавить критерий</button></div>
      <div class="stack small" style="padding:12px 10px 4px;gap:4px"><span class="label">Версии</span>${S.versions.slice().reverse().map(v => `<span>v${esc(v.v)}: ${esc(v.note)}${v.v === cl.version ? ' <span class="chip c-ok">применяется</span>' : ''}</span>`).join('')}</div>
    </section>
    ${c ? editor(S, c) : '<section class="card empty">Критериев нет. Добавьте первый.</section>'}
  </div>`;
}

function editor(S, c) {
  const field = (k, id) => `id="cf-${id}" class="fld" data-act="cf" data-cf="${k}"`;
  return `<section class="card pad" aria-label="Редактор критерия"><fieldset class="stack" style="gap:16px" ${S.role === 'qa' ? '' : 'disabled'}>
      <legend class="row" style="justify-content:space-between;width:100%;margin-bottom:12px"><span class="h2">Критерий ${esc(c.id)}</span>${S.role !== 'qa' ? '<span class="chip c-na">Только просмотр: редактирует специалист КК</span>' : ''}</legend>
      <div class="grid2">
        <label class="field"><span>Название</span><input ${field('name', 'name')} value="${esc(c.name)}"></label>
        <label class="field"><span>Секция</span><select ${field('sec', 'sec')}>${opts(S.draft.sections.map((s, i) => [i, s]), c.sec)}</select></label>
      </div>
      <label class="field"><span>Что проверяем</span><textarea ${field('text', 'text')}>${esc(c.text)}</textarea><span class="muted xs">Этот текст модель получает дословно. Названий критериев нет ни в коде, ни в промпте.</span></label>
      <div class="grid2">
        <label class="field"><span>Тип ответа</span><select ${field('type', 'type')}>${opts(TYPES, c.type)}</select></label>
        ${c.type !== 'flag' ? `<label class="field"><span>Вес</span><input ${field('w', 'w')} type="number" min="0" max="100" value="${esc(c.w)}"></label>` : '<span></span>'}
      </div>
      ${c.type !== 'flag' ? `<div class="stack box na" style="gap:8px"><label class="row" style="gap:8px;font-weight:600"><input id="cf-na" type="checkbox" data-act="cf" data-cf="na" ${c.na ? 'checked' : ''}>N/A разрешён</label>
        ${c.na ? `<label class="field"><span>Условие N/A</span><input ${field('naCond', 'nac')} value="${esc(c.naCond || '')}"></label>` : ''}</div>` : ''}
      ${c.type === 'scale' ? `<label class="field"><span>Ступени шкалы, по строке на ступень: «балл: что значит»</span><textarea ${field('steps', 'steps')} style="min-height:130px">${esc((c.steps || []).map(s => `${s}: ${(c.stepText || {})[s] || ''}`).join('\n'))}</textarea><span class="muted xs">Верхняя ступень даёт полный вес, остальные пропорционально.</span></label>` : ''}
      ${c.type === 'flag' ? `<label class="field"><span>Подвопросы, по строке на вид нарушения</span><textarea ${field('questions', 'q')}>${esc((c.questions || []).map(q => q.label).join('\n'))}</textarea><span class="muted xs">Каждый подвопрос идёт к модели отдельно. Флаг ставится, если выполнен хотя бы один.</span></label>` : ''}
      <div class="grid2">
        <label class="field"><span>Канал</span><select ${field('channel', 'ch')}>${opts(CHANNELS, c.channel || 'all')}</select><span class="muted xs">Для одного канала нужен N/A: на другом критерий не оценивается.</span></label>
        <label class="field"><span>Сигнал для списка и аналитики</span><select ${field('signal', 'sig')}>${opts(SIGNALS, c.signal || '')}</select>
          <span class="muted xs">Метка «Без следующего шага» и плитки аналитики строятся по сигналу, а не по номеру критерия, поэтому замена критерия их не ломает.</span></label>
      </div>
      <div class="row only-qa" style="justify-content:space-between;border-top:1px solid var(--line2);padding-top:14px">
        <span class="muted small">Смена веса пересчитывает итоги сразу. Смена текста, типа, шкалы или N/A требует новой оценки этого критерия.</span>
        <button type="button" class="btn" data-act="cdel">Удалить критерий</button></div>
    </fieldset></section>`;
}

function setField(t) {
  const c = selected(), k = t.dataset.cf;
  if (k === 'w') c.w = Number(t.value) || 0;
  else if (k === 'sec') c.sec = Number(t.value);
  else if (k === 'na') c.na = t.checked;
  else if (k === 'signal') { if (t.value) c.signal = t.value; else delete c.signal; }
  else if (k === 'channel') { c.channel = t.value; if (t.value !== 'all') c.na = true; } // контракт: канал без N/A — 422
  else if (k === 'type') {
    c.type = t.value;
    if (c.type === 'scale' && !c.steps) { c.steps = [10, 5, 0]; c.stepText = { 10: 'Полностью', 5: 'Частично', 0: 'Нет' }; }
    if (c.type === 'flag' && !c.questions) c.questions = [{ k: 'q1', label: 'Нарушение' }];
  } else if (k === 'steps') {
    const lines = t.value.split('\n').map(s => s.match(/^\s*(\d+)\s*[:—-]?\s*(.*)$/)).filter(Boolean);
    if (lines.length) {
      c.steps = lines.map(m => Number(m[1])).sort((a, b) => b - a);
      c.stepText = Object.fromEntries(lines.map(m => [m[1], m[2]]));
    }
  } else if (k === 'questions') {
    c.questions = t.value.split('\n').map(s => s.trim()).filter(Boolean)
      .map((label, i) => ({ ...(c.questions?.[i] || { k: 'q' + (i + 1) }), label }));
  } else c[k] = t.value;
}

// csave и crun неактивны, пока запрос в пути: двойной клик не создаёт две версии или два запуска
async function busy(request) {
  S.busy = true;
  render();
  try { await request(); } finally { S.busy = false; render(); }
}

export const actions = {
  csel: t => { S.cSel = t.dataset.cid; render(); },
  cf: t => { setField(t); render(); },
  cadd: () => {
    const dr = S.draft, id = String(Math.max(0, ...dr.criteria.map(c => Number(c.id)).filter(Number.isFinite)) + 1).padStart(2, '0');
    dr.criteria.push({ id, sec: Math.max(0, dr.sections.length - 2), name: 'Новый критерий', type: 'bool', w: 5, na: false, text: 'Да — …', channel: 'all' });
    S.cSel = id;
    render();
  },
  cdel: () => { S.draft.criteria = S.draft.criteria.filter(c => c.id !== S.cSel); S.cSel = null; render(); },
  creset: () => { S.draft = null; render(); },
  csave: () => busy(async () => {
    try {
      const { version, pending } = await api.putChecklist(S.draft);
      S.pending = [...new Set([...(S.pending || []), ...pending])];
      await reload();
      toast(pending.length ? `Сохранена версия v${version}. Критерии ${pending.join(', ')} ждут оценки.` : `Сохранена версия v${version}. Итоги пересчитаны без вызова модели.`);
    } catch (e) {
      toast(`Чек-лист не сохранён: ${e.message}`);
    }
  }),
  crun: () => busy(() => startRun({ dialogs: null, criteria: waiting() })),
};
