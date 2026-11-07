// Экран решений по апелляциям: очередь слева, рассмотрение справа, история решений (прототип, раздел 3).
import { S, api, reload, render, toast } from '../state.js';
import { calc } from '../scoring.js';
import { esc, titleOf, f2, mmss, ansTxt } from '../format.js';
import { href } from '../router.js';
import { allowed, answerOf, signOf } from '../appeal_form.js';

// Черновики решений по id апелляции: режим, выбранный ответ, причина. Живут до сохранения.
const DEC = {};
const MIN_REASON = 5;

const crit = cid => S.checklist.criteria.find(c => c.id === cid);
const dlg = id => S.dialogs.find(d => d.id === id);
const txt = (c, v) => (c ? ansTxt(c, v) : String(v));
const step = v => (v === 'yes' ? 'Да' : v === 'no' ? 'Нет' : v === 'na' ? 'N/A' : v);
const WHO = { client: 'клиент', operator: 'оператор', bot: 'бот', system: 'система' };
const STATUS = {
  pending: ['c-ev', 'Ждёт решения', ''],
  changed: ['c-info', 'Оценка изменена', ', изменена'],
  confirmed: ['c-ok', 'Оценка подтверждена', ', подтверждена'],
  closed: ['c-na', 'Закрыта', ', закрыта'],
};
const draft = a => (DEC[a.id] ||= { mode: 'change', val: a.ask, reason: '' });
const target = (a, st) => (st.mode === 'confirm' ? a.from : st.val);

export function view(S, id) {
  const list = S.appeals.filter(a => a.kind === 'appeal');
  const pend = list.filter(a => a.status === 'pending'), done = list.filter(a => a.status !== 'pending');
  const a = list.find(x => x.id === id) || pend[0] || done[0];
  const item = x => {
    const c = crit(x.cid), d = dlg(x.dlg);
    return `<a class="qitem" href="${href('appeals', x.id)}" aria-current="${a === x}"><span class="row" style="justify-content:space-between"><b>${esc(d ? titleOf(d) : x.dlg)}</b><span class="muted xs">${esc(x.at)}</span></span>
      <span class="small">${esc(x.cid)} ${esc(c ? c.name : '')}</span><span class="muted xs">${esc(txt(c, x.from))} → просят ${esc(txt(c, x.ask))}${STATUS[x.status][2]}</span></a>`;
  };
  const decided = S.appeals.filter(x => x.status === 'changed' || x.status === 'confirmed')
    .sort((x, y) => (y.decidedAt || '').localeCompare(x.decidedAt || ''));
  return `
  <div class="head"><div><h1 class="h1">Апелляции</h1><p class="sub">Спорная оценка, довод и фрагмент разговора на одном экране</p></div></div>
  <div class="split">
    <aside class="card" style="padding:8px" aria-label="Очередь апелляций">
      <p class="label" style="padding:6px 12px">Ждут решения: ${pend.length}</p>${pend.map(item).join('') || '<p class="muted small" style="padding:0 12px 8px">Очередь пуста.</p>'}
      <p class="label" style="padding:14px 12px 6px">Решённые: ${done.length}</p>${done.map(item).join('')}
    </aside>
    <div class="stack" style="gap:14px">${a ? detail(a) : '<div class="card empty">Апелляций пока нет. Оспорить оценку можно в карточке разговора.</div>'}
      <section class="card pad" aria-label="История решений"><h2 class="h2" style="margin-bottom:12px">История решений</h2><div class="timeline">
        ${decided.map(x => { const c = crit(x.cid), d = dlg(x.dlg); return `<div class="ev"><i class="${x.status === 'changed' ? '' : 'k'}"></i><div>
          <b>${esc(d ? titleOf(d) : x.dlg)}, ${esc(x.cid)}: ${x.status === 'changed' ? `${esc(txt(c, x.from))} → ${esc(txt(c, x.to))}` : 'оценка подтверждена'}</b>
          <p class="muted small">${esc(x.reviewer)}, ${esc(x.decidedAt)}. ${esc(x.reason)}</p></div></div>`; }).join('') || '<p class="muted small">Решений пока нет.</p>'}
      </div></section>
    </div>
  </div>`;
}

function fragment(d, r, a) {
  const mine = r.ev || [], theirs = a.ev || [];
  const ns = [...mine, ...theirs];
  if (!d.lines || !ns.length) return '<p class="muted small">Реплик-оснований нет.</p>';
  const lo = Math.min(...ns) - 2, hi = Math.max(...(mine.length ? mine : ns)) + 1;
  return d.lines.filter(l => !l.fold && ((l.n >= lo && l.n <= hi) || theirs.includes(l.n))).map(l => {
    const m = mine.includes(l.n), ap = theirs.includes(l.n);
    return `<div class="quote" data-n="${l.n}" style="${m ? 'background:var(--ev-soft);border-color:var(--ev-line)' : ap ? 'background:var(--info-soft);border-color:var(--info-line)' : ''}"><div><span class="muted xs">${l.n}, ${WHO[l.who] || ''}${m ? ', основание модели' : ''}${ap ? ', довод оспаривающего' : ''}</span><br>${esc(l.text)}</div>
      ${d.ch === 'call' && l.s != null ? `<a class="btn sm" href="${href('d', d.id)}">▶ ${mmss(l.s)}</a>` : ''}</div>`;
  }).join('');
}

function detail(a) {
  const d = dlg(a.dlg), c = crit(a.cid);
  if (!d || !c) return `<section class="card empty" aria-label="Рассмотрение">Критерий ${esc(a.cid)} удалён из чек-листа или диалог не найден. Апелляция закрыта без решения.</section>`;
  const r = d.res[a.cid] || {};
  const [cls, label] = STATUS[a.status];
  let out = `<section class="card pad stack" style="gap:14px" aria-label="Рассмотрение">
    <div class="row" style="justify-content:space-between"><div><h2 class="h2">${esc(titleOf(d))}, ${esc(c.id)} ${esc(c.name)}</h2>
      <p class="muted small">Подал: ${esc(a.by)}, ${esc(a.at)}. Вес критерия ${c.w}. <a href="${href('d', d.id)}">Открыть карточку</a></p></div>
      <span class="chip ${cls}">${label}</span></div>
    <div class="compare">
      <div><span class="label">Оценка модели</span><strong>${esc(ansTxt(c, a.from))}</strong><span class="small">${esc(r.why || '')}</span>${r.alt != null ? `<span class="small" style="color:var(--info)">Второе мнение: ${esc(ansTxt(c, r.alt))}</span>` : ''}</div>
      <div><span class="label">Просит оспаривающий</span><strong>${esc(ansTxt(c, a.ask))}</strong><span class="small">«${esc(a.comment)}»</span></div>
    </div>
    <div class="stack" style="gap:6px"><span class="label">Фрагмент разговора</span>${fragment(d, r, a)}</div>`;
  if (a.status === 'closed') {
    out += '<div class="box na">Критерий изменён или удалён новой версией чек-листа. Апелляция закрыта без решения.</div>';
  } else if (a.status !== 'pending') {
    out += `<div class="box ${a.status === 'changed' ? 'info' : 'good'}"><b>${esc(a.reviewer)}, ${esc(a.decidedAt)}:</b> ${esc(a.reason)}</div>`;
  } else {
    const st = draft(a);
    const before = calc(d, S.checklist, S.appeals).total;
    const after = calc(d, S.checklist, S.appeals, { cid: a.cid, val: target(a, st) }).total;
    out += `
    <p class="only-rv-note box na">Решение принимает проверяющий. Переключите роль вверху страницы, чтобы показать этот шаг.</p>
    <fieldset class="only-rv stack" style="gap:14px;border-top:1px solid var(--line2);padding-top:14px">
      <legend class="h2" style="margin-bottom:10px">Решение проверяющего</legend>
      <div class="row">
        <label class="opt"><input type="radio" name="dm" value="confirm" data-act="dmode" data-id="${a.id}" ${st.mode === 'confirm' ? 'checked' : ''}>Подтвердить оценку модели</label>
        <label class="opt"><input type="radio" name="dm" value="change" data-act="dmode" data-id="${a.id}" ${st.mode === 'change' ? 'checked' : ''}>Изменить оценку</label>
      </div>
      ${st.mode === 'change' ? `<div class="stack" style="gap:6px"><span class="field"><span>Новый ответ</span></span><div class="ladder" role="group" aria-label="Новый ответ">
        ${allowed(c).map(v => `<button type="button" class="step" data-act="dval" data-id="${a.id}" data-v="${v}" aria-pressed="${v === st.val}">${step(v)}</button>`).join('')}</div>
        ${c.type === 'scale' && c.stepText && c.stepText[st.val] ? `<span class="muted xs">${st.val}: ${esc(c.stepText[st.val])}</span>` : ''}
        <span class="muted xs">Доступны только ${c.type === 'scale' ? 'ступени шкалы' : 'ответы «Да» и «Нет»'}${c.na ? ' и N/A, он разрешён у этого критерия' : ''}.</span></div>` : ''}
      <label class="field"><span>Причина решения, обязательно</span><textarea id="decReason" class="fld" data-act="dreason" data-input data-id="${a.id}" placeholder="Например: регламент не позволяет называть срок, следующий шаг дан полностью">${esc(st.reason)}</textarea></label>
      <div class="row" style="justify-content:space-between;border-top:1px solid var(--line2);padding-top:12px">
        <span>Итог разговора: <s class="muted">${f2(before)}</s> → <b style="font-size:20px">${f2(after)}</b></span>
        <button type="button" class="btn pri" data-act="decide" data-id="${a.id}" ${st.reason.trim().length < MIN_REASON ? 'disabled' : ''}>Сохранить решение</button>
      </div>
    </fieldset>`;
  }
  return out + '</section>';
}

export const actions = {
  dmode: t => { DEC[t.dataset.id].mode = t.value; render(); },
  dval: t => { DEC[t.dataset.id].val = answerOf(t.dataset.v); render(); },
  dreason: t => {
    DEC[t.dataset.id].reason = t.value;
    S.app.querySelector('[data-act="decide"]').disabled = t.value.trim().length < MIN_REASON;
  },
  decide: async t => {
    const a = S.appeals.find(x => x.id === t.dataset.id), st = DEC[a.id];
    const before = calc(dlg(a.dlg), S.checklist, S.appeals).total;
    t.disabled = true;
    try {
      await api.postDecision(a.id, { to: target(a, st), reason: st.reason.trim(), reviewer: signOf(S.role) });
    } catch (e) {
      t.disabled = false;
      toast(`Решение не сохранено: ${e.message}`);
      return;
    }
    delete DEC[a.id];
    await reload();
    const d = dlg(a.dlg);
    toast(`Решение сохранено. Итог ${titleOf(d)}: ${f2(before)} → ${f2(calc(d, S.checklist, S.appeals).total)}.`);
  },
};
