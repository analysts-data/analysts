// Экран «Обучение» (analytics-coaching, группа 4): обратная связь на конкретных репликах, разбор для встречи.
import { coachingStats, goodExamples } from '../analytics.js';
import { ansTxt, esc, titleOf } from '../format.js';
import { href } from '../router.js';
import { render, toast } from '../state.js';

const LANG = { RU: 'Русский', KZ: 'Қазақша', EN: 'English' };
let selected = null;
const sheet = new Set();

export function view(S) {
  const groups = coachingStats(S).groups;
  if (!groups.some(g => g.cid === selected)) selected = groups[0]?.cid ?? null;
  const crit = id => S.checklist.criteria.find(c => c.id === id);
  const dlg = id => S.dialogs.find(d => d.id === id);
  const sel = groups.find(g => g.cid === selected);
  const c = selected && crit(selected);
  const all = groups.flatMap(g => g.items.map(x => ({ ...x, c: crit(g.cid) })));
  const picked = all.filter(x => sheet.has(x.key));
  const good = c ? goodExamples(S, c.id) : [];
  return `
  <div class="head"><div><h1 class="h1">Обучение</h1><p class="sub">Обратная связь на конкретных репликах из наших разговоров</p></div>
    <button type="button" class="btn pri no-print" data-act="sheet">Разбор для встречи: ${picked.length}</button></div>
  ${groups.length ? `<div class="seg no-print" role="group" aria-label="Критерий" style="align-self:flex-start;flex-wrap:wrap">
    ${groups.map(g => `<button type="button" data-act="coach" data-cid="${esc(g.cid)}" aria-pressed="${g.cid === selected}">${esc(g.cid)} ${esc(crit(g.cid).name)}: ${g.items.length}</button>`).join('')}</div>` : ''}
  <div class="cols no-print">
    <section class="stack" aria-label="Где теряем баллы"><h2 class="h2">Где теряем баллы</h2>
      ${sel ? sel.items.map(x => { const d = dlg(x.dialogId);
        return `<article class="card pad stack">
          <div class="row" style="justify-content:space-between"><span class="small"><a href="${esc(href('d', x.dialogId))}">${esc(titleOf(d))}</a>, ${esc(LANG[x.lang] || x.lang)}</span><span class="chip ${c.type === 'bool' ? 'c-risk' : 'c-ev'}">${esc(ansTxt(c, x.answer))}</span></div>
          ${x.line ? `<p style="font-size:15px">«${esc(x.line.text)}»</p>` : ''}
          <p class="small"><b>Что не так:</b> ${esc(x.why)}</p>
          <div class="box good"><b>Как сказать лучше:</b> «${esc(x.better)}»</div>
          <label class="row small" style="gap:8px"><input type="checkbox" data-act="pick" data-key="${esc(x.key)}" ${sheet.has(x.key) ? 'checked' : ''}>Добавить в разбор</label>
        </article>`; }).join('') : '<div class="card empty">Подсказок пока нет: они появятся после оценки, где модель снизила балл и предложила формулировку.</div>'}
    </section>
    <section class="stack" aria-label="Как звучит хороший ответ"><h2 class="h2">Как звучит хороший ответ</h2>
      ${good.map(g => `<article class="card pad stack"><div class="row" style="justify-content:space-between"><span class="small"><a href="${esc(href('d', g.dialogId))}">${esc(titleOf(dlg(g.dialogId)))}</a>, реплика ${g.lineNo}</span><span class="chip c-ok">полный балл</span></div><p style="font-size:15px">«${esc(g.text)}»</p></article>`).join('')
        || `<div class="card pad muted">В наборе пока нет ответа с полным баллом и цитатой оператора по критерию «${esc(c ? c.name : '')}». Примеры появятся, когда модель даст полный балл с основанием.</div>`}
    </section>
  </div>
  <section class="card pad stack" id="sheet" aria-label="Разбор для встречи с оператором">
    <div class="row" style="justify-content:space-between"><h2 class="h2">Разбор для встречи с оператором</h2>
      <div class="row no-print"><button type="button" class="btn" data-act="copy" ${picked.length ? '' : 'disabled'}>Скопировать текст</button><button type="button" class="btn" data-act="print" ${picked.length ? '' : 'disabled'}>Печать</button></div></div>
    ${picked.length ? `<ol class="stack" style="padding-left:20px;margin:0">${picked.map(x => `<li><b>${esc(titleOf(dlg(x.dialogId)))}, ${esc(x.c.name)}.</b> ${esc(x.why)} Лучше: «${esc(x.better)}»</li>`).join('')}</ol>`
      : '<p class="muted">Отметьте моменты выше, и они соберутся в один лист для встречи.</p>'}
  </section>`;
}

export const actions = {
  coach: t => { selected = t.dataset.cid; render(); },
  pick: t => { if (t.checked) sheet.add(t.dataset.key); else sheet.delete(t.dataset.key); render(); },
  sheet: () => document.getElementById('sheet').scrollIntoView({ block: 'start' }),
  copy: () => navigator.clipboard.writeText(document.querySelector('#sheet ol').innerText)
    .then(() => toast('Текст разбора скопирован.'), () => toast('Браузер не дал доступа к буферу обмена. Выделите текст вручную.')),
  print: () => window.print(),
};
