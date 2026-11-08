// Редактор чек-листа: черновик — копия применяемой версии, правки живут в браузере до сохранения.
import { S, api, reload, render, startRun, toast } from '../state.js';
import { esc, fn } from '../format.js';
import { runErrors } from './queue.js';
import { importQuestions, exportQuestions, syncJev } from '../checklist_json.js';

const SIGNALS = [['', 'Нет'], ['resolution', 'Решение запроса'], ['risk', 'Риск']];
const TYPES = [['bool', 'Да / Нет'], ['scale', 'Шкала'], ['flag', 'Флаг нарушения, без баллов']];
const TYPE_NAME = { bool: 'Да/Нет', scale: 'Шкала', flag: 'Флаг' };
const CHANNELS = [['all', 'Все каналы'], ['chat', 'Чат'], ['call', 'Звонок']];

const scored = cl => cl.criteria.filter(c => c.type !== 'flag');
const wsum = cs => cs.reduce((s, x) => s + (Number(x.w) || 0), 0);
const opts = (list, cur) => list.map(([v, t]) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${esc(t)}</option>`).join('');
const selected = () => S.draft.criteria.find(x => x.id === S.cSel);
// pending приходит только из ответа PUT /api/checklist и держится, пока критерий есть в версии и у диалогов нет его записи
const waiting = () => (S.pending || []).filter(cid => S.checklist.criteria.some(c => c.id === cid) && S.dialogs.some(d => !d.res[cid]));

export function view(S) {
  // новая версия с сервера сбрасывает черновик; если сохранение упало, правки остаются
  if (S.draft?.version !== S.checklist.version) S.draft = structuredClone(S.checklist);
  const cl = S.checklist, dr = S.draft, pend = waiting(), run = S.run?.status === 'running' ? S.run : null;
  const errs = runErrors(S.run); // запуск с ошибками остаётся на баннере до следующего запуска
  const c = selected() || dr.criteria[0];
  S.cSel = c?.id;
  const sum = wsum(scored(dr));
  const dirty = JSON.stringify(dr) !== JSON.stringify(cl);
  const changed = id => {
    const o = cl.criteria.find(x => x.id === id), n = dr.criteria.find(x => x.id === id);
    // правила входят в смысл каждого критерия: сервер вернёт в pending весь чек-лист
    return dr.rules !== cl.rules || !o || JSON.stringify(o) !== JSON.stringify(n);
  };
  return `
  <div class="head"><div><h1 class="h1">Чек-лист качества</h1><p class="sub">Версия ${cl.version} применяется к набору. Изменения сохраняются новой версией.</p></div>
    <div class="row">${dirty ? '<span class="chip c-ev only-qa">Есть несохранённые изменения</span>' : ''}
      ${exportMenu(S)}
      <label class="btn only-qa">Загрузить из файла<input type="file" accept=".json,application/json" data-act="cimport" class="sr" ${dirty ? 'disabled' : ''}></label>
      <button type="button" class="btn only-qa" data-act="creset" ${dirty ? '' : 'disabled'}>Отменить изменения</button>
      <button type="button" class="btn only-qa" data-act="cwhat" ${dirty ? '' : 'disabled'}>Что изменится</button>
      <button type="button" class="btn pri only-qa" data-act="csave" ${dirty && !S.busy ? '' : 'disabled'}>Сохранить как v${cl.version + 1}</button></div></div>
  ${S.role === 'qa' ? `<section class="card pad row" aria-label="Формат Jev">
    <label class="btn">Импорт из формата Jev<input type="file" accept=".json,application/json" data-act="cjevimport" class="sr" ${S.busy ? 'disabled' : ''}></label>
    <button type="button" class="btn" data-act="cjevexport">Экспорт в формат Jev</button>
    <span class="muted small">Вопросы Jev (questions). Импорт обновляет черновик по ID, веса настраиваются отдельно.</span>
  </section>` : ''}
  ${pend.length || run || errs ? `<section class="card pad row" style="justify-content:space-between;background:var(--ev-soft);border-color:var(--ev-line)">
    <span>${pend.length ? `Критерии ${pend.map(esc).join(', ')} ждут оценки: <b>${pend.length * S.dialogs.length} вызовов</b> основной модели, остальные ответы берутся из кэша.` : ''}
      ${run ? `Оценено <b>${run.done} из ${run.total}</b> ответов по критериям, $${fn(run.cost)}${run.eta_s != null ? `, осталось около ${Math.ceil(run.eta_s)} с` : ''}.` : ''}</span>
    <span class="row only-qa">${run ? '<button type="button" class="btn" data-act="stop">Остановить</button>' : ''}
      ${pend.length ? `<button type="button" class="btn pri" data-act="crun" ${run || S.busy ? 'disabled' : ''}>${run ? 'Идёт оценка…' : 'Оценить набор'}</button>` : ''}</span>${errs}</section>` : ''}
  <div class="split" style="grid-template-columns:minmax(0,.9fr) minmax(0,1.3fr)">
    <section class="card" style="padding:10px" aria-label="Структура чек-листа">
      ${dr.sections.map((s, si) => `<p class="label row" style="justify-content:space-between;padding:8px 10px 4px"><span>${esc(s)}</span><span>${wsum(scored(dr).filter(x => x.sec === si)) || ''}</span></p><div class="clist">
        ${dr.criteria.filter(x => x.sec === si).map(x => `<button type="button" class="citem" data-act="csel" data-cid="${esc(x.id)}" aria-current="${x.id === S.cSel}"><span class="muted small">${esc(x.id)}</span><span>${esc(x.name)}${changed(x.id) ? ' <span class="chip c-ev">изменён</span>' : ''}${pend.includes(x.id) ? ' <span class="chip c-ev">ждёт оценки</span>' : ''}${x.signal ? ` <span class="chip c-info">${esc(SIGNALS.find(s => s[0] === x.signal)?.[1] ?? x.signal)}</span>` : ''}</span><span class="muted xs">${TYPE_NAME[x.type] ?? esc(x.type)}${x.na ? ', N/A' : ''}</span><b class="num">${x.type === 'flag' ? '—' : esc(x.w)}</b></button>`).join('')}</div>`).join('')}
      <div class="row" style="padding:12px 10px 4px;border-top:1px solid var(--line2);margin-top:8px">
        <span class="chip ${sum === 100 ? 'c-ok' : 'c-ev'}">Сумма весов ${sum}</span>${sum !== 100 ? '<span class="muted xs">Итог всё равно приводится к 100</span>' : ''}
        <button type="button" class="btn sm only-qa" data-act="cadd" style="margin-left:auto">Добавить критерий</button></div>
      <div class="stack small" style="padding:12px 10px 4px;gap:4px"><span class="label">Версии</span>${S.versions.slice().reverse().map(v => `<span>v${esc(v.v)}: ${esc(v.note)}${v.v === cl.version ? ' <span class="chip c-ok">применяется</span>' : ` <button type="button" class="btn sm" data-act="cdiff" data-v="${esc(v.v)}">Сравнить с текущей</button>`}</span>`).join('')}</div>
    </section>
    ${c ? editor(S, c) : '<section class="card empty">Критериев нет. Добавьте первый.</section>'}
  </div>
  ${rulesEditor(S)}`;
}

// Файлы строит сервер (GET /api/checklist/export): пункты — обычные ссылки, по умолчанию применяемая версия.
// Смена версии в списке переписывает ссылки на месте (actions.cexpv): перерисовка закрыла бы меню.
function exportMenu(S) {
  const v = S.checklist.version;
  const link = (fmt, label, attrs) => `<a class="btn sm" href="${esc(api.exportUrl(v, fmt))}" data-fmt="${fmt}" ${attrs}>${label}</a>`;
  return `<details class="menu"><summary class="btn">Экспорт ▾</summary><div class="menu-pop card stack">
    <label class="field"><span>Версия</span><select class="fld" data-act="cexpv">${opts(S.versions.slice().reverse().map(x => [x.v, `v${x.v}${x.v === v ? ' — применяется' : ''}`]), v)}</select></label>
    ${link('json', 'JSON', 'data-act="cexport" download')}
    ${link('csv', 'Excel (CSV)', 'data-act="cmenu" download')}
    ${link('md', 'Markdown', 'data-act="cmenu" download')}
    ${link('html', 'Памятка для печати', 'data-act="cmenu" target="_blank" rel="noopener"')}
  </div></details>`;
}

// Разницу считает сервер (Markdown), окно показывает её как текст
async function showDiff(title, load) {
  let md;
  try { md = await load(); } catch (e) { return toast(`Сравнение не получено: ${e.message}`); }
  const form = S.app.querySelector('#dlgForm');
  form.innerHTML = `<header><h2 class="h2" id="dlgTitle">${esc(title)}</h2></header>
    <pre class="diff">${esc(md.trimEnd())}</pre>
    <footer><button class="btn pri" value="cancel">Закрыть</button></footer>`;
  form.closest('dialog').showModal();
}

const closeMenu = t => { t.closest('details').open = false; }; // ссылка всё равно срабатывает

// Общие правила — часть черновика, сохраняются тем же PUT /api/checklist (см. actions.crules)
function rulesEditor(S) {
  return `<section class="card pad" aria-label="Общие правила"><fieldset ${S.role === 'qa' ? '' : 'disabled'}>
    <label class="field"><span>Общие правила</span><textarea id="cl-rules" class="fld" data-act="crules" data-input style="min-height:150px">${esc(S.draft.rules)}</textarea>
      <span class="muted xs">Модель получает правила вместе с каждым критерием. Смена правил меняет смысл всех критериев: после сохранения весь чек-лист ждёт новой оценки.</span></label>
  </fieldset></section>`;
}

function editor(S, c) {
  // текст — data-input: черновик меняется на каждый ввод, а не при уходе из поля (см. actions.cf)
  const field = (k, id) => `id="cf-${id}" class="fld" data-act="cf" data-cf="${k}"${TYPED.has(k) ? ' data-input' : ''}`;
  return `<section class="card pad" aria-label="Редактор критерия"><fieldset class="stack" style="gap:16px" ${S.role === 'qa' ? '' : 'disabled'}>
      <legend class="row" style="justify-content:space-between;width:100%;margin-bottom:12px"><span class="h2">Критерий ${esc(c.id)}</span>${S.role !== 'qa' ? '<span class="chip c-na">Только просмотр: редактирует специалист КК</span>' : ''}</legend>
      <div class="grid2">
        <label class="field"><span>Название</span><input ${field('name', 'name')} value="${esc(c.name)}"></label>
        <label class="field"><span>Секция</span><select ${field('sec', 'sec')}>${opts(S.draft.sections.map((s, i) => [i, s]), c.sec)}</select></label>
      </div>
      <label class="field"><span>Что проверяем</span><textarea ${field('text', 'text')}>${esc(c.text)}</textarea><span class="muted xs">Этот текст модель получает дословно. Названий критериев нет ни в коде, ни в промпте.</span></label>
      ${callField(c, field)}
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
        <span class="muted small">Смена веса пересчитывает итоги сразу. Смена текста, типа, шкалы или N/A требует новой оценки этого критерия, смена уточнения для звонка — только на звонках.</span>
        <button type="button" class="btn" data-act="cdel">Удалить критерий</button></div>
    </fieldset></section>`;
}

// Уточнение для звонка — для любого типа; пустое поле убирает ключ, сервер читает это как call: null
function callField(c, field) {
  return `<label class="field"><span>Уточнение для звонка</span><textarea ${field('call', 'call')} style="min-height:64px">${esc(c.call || '')}</textarea>
    <span class="muted xs">Необязательно. Модель получает его только на звонках, запрос по чатам не меняется.</span></label>`;
}

function setCall(c, value) {
  if (value.trim()) c.call = value;
  else delete c.call; // без ключа черновик совпадает с версией с сервера (там нет null-полей)
}

function setField(t) {
  const c = selected(), k = t.dataset.cf;
  if (k === 'w') c.w = Number(t.value) || 0;
  else if (k === 'sec') c.sec = Number(t.value);
  else if (k === 'na') c.na = t.checked;
  else if (k === 'signal') { if (t.value) c.signal = t.value; else delete c.signal; }
  else if (k === 'call') setCall(c, t.value);
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
  syncJev(c, k === 'channel' ? 'na' : k);
}

const TYPED = new Set(['name', 'text', 'naCond', 'call']);

// Текстовые поля не перерисовывают экран ни на ввод, ни на change: перерисовка по change
// (уход из поля) приходится на нажатие «Сохранить» и съедает клик. Кнопки — по черновику.
function syncSave() {
  const dirty = JSON.stringify(S.draft) !== JSON.stringify(S.checklist);
  S.app.querySelector('[data-act="creset"]').disabled = !dirty;
  S.app.querySelector('[data-act="csave"]').disabled = !dirty || S.busy;
  S.app.querySelector('[data-act="cwhat"]').disabled = !dirty;
  S.app.querySelector('[data-act="cimport"]').disabled = dirty; // импорт не стирает несохранённые правки
}

// csave и crun неактивны, пока запрос в пути: двойной клик не создаёт две версии или два запуска
async function busy(request) {
  S.busy = true;
  render();
  try { await request(); } finally { S.busy = false; render(); }
}

export const actions = {
  // формат Jev: вопросы сливаются в черновик по ID, несохранённые правки остаются
  cjevimport: async t => {
    const file = t.files[0];
    t.value = '';
    if (!file || S.role !== 'qa' || S.busy) return;
    S.busy = true;
    render();
    try {
      const text = await file.text();
      if (S.role !== 'qa') return;
      const result = importQuestions(S.draft, JSON.parse(text.replace(/^\uFEFF/, '')));
      S.draft = result.draft;
      toast(`Добавлено ${result.added}, обновлено ${result.updated}. Проверьте веса и сохраните версию.`);
    } catch (e) { toast(`Импорт не выполнен: ${e.message}`); }
    finally { S.busy = false; render(); }
  },
  cjevexport: () => {
    if (S.role !== 'qa') return;
    try {
      const blob = new Blob([JSON.stringify(exportQuestions(S.draft), null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = `questions-v${S.draft.version}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (S.draft.criteria.some(c => c.type === 'flag')) toast('Флаги экспортированы отдельными noul-вопросами с ID «критерий_подвопрос».');
    } catch (e) { toast(`Экспорт не выполнен: ${e.message}`); }
  },
  csel: t => { S.cSel = t.dataset.cid; render(); },
  cf: t => { setField(t); if (TYPED.has(t.dataset.cf)) syncSave(); else render(); },
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
      if (S.run?.status !== 'running') S.run = null; // итог прошлого запуска относится к прежней версии
      await reload();
      toast(pending.length ? `Сохранена версия v${version}. Критерии ${pending.join(', ')} ждут оценки.` : `Сохранена версия v${version}. Итоги пересчитаны без вызова модели.`);
    } catch (e) {
      toast(`Чек-лист не сохранён: ${e.message}`);
    }
  }),
  crun: () => busy(() => startRun({ dialogs: null, criteria: waiting() })),
  crules: t => { S.draft.rules = t.value; syncSave(); },
  // в файл — сохранённая версия (по умолчанию применяемая), а не черновик
  cexport: closeMenu,
  cmenu: closeMenu,
  cexpv: t => t.closest('details').querySelectorAll('a[data-fmt]').forEach(a => { a.href = api.exportUrl(t.value, a.dataset.fmt); }),
  cdiff: t => showDiff(`Сравнение v${t.dataset.v} с текущей v${S.checklist.version}`, () => api.diffVersions(t.dataset.v, S.checklist.version)),
  // черновик уходит на сервер как есть (POST /api/checklist/diff): та же разница, что у версий, ничего не сохраняется
  cwhat: () => showDiff(`Что изменится при сохранении v${S.checklist.version + 1}`, () => api.diffDraft(S.draft)),
  // файл — в черновик с текущей версией (иначе view() сбросит черновик, а сервер ответит 409); остальное проверит сервер при сохранении
  cimport: async t => {
    const f = t.files[0];
    t.value = '';
    if (!f) return;
    let cl = null;
    try { cl = JSON.parse(await f.text()); } catch { /* не JSON */ }
    if (!Array.isArray(cl?.sections) || !Array.isArray(cl?.criteria)) return toast('Файл не похож на чек-лист: нужны поля sections и criteria.');
    S.draft = { ...cl, version: S.checklist.version };
    S.cSel = null;
    render();
    toast(`Чек-лист из файла в черновике. Проверьте изменения и сохраните как v${S.checklist.version + 1}.`);
  },
};
