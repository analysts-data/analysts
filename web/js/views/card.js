// Карточка разговора: сводка, критерии по секциям, расшифровка со свёрнутыми участками (прототип, «2. Карточка»).
import { S, api, render } from '../state.js';
import { ans, calc, flagsOf, frac, lastDec } from '../scoring.js';
import { groupOf, queueOrder } from '../queue.js';
import { ansTxt, esc, f2, fn, mmss, titleOf } from '../format.js';
import { href } from '../router.js';
import * as player from '../player.js';

const LANG = { RU: 'Русский', KZ: 'Қазақша', EN: 'English' };
const WHO = { client: 'клиент', operator: 'оператор', bot: 'бот', system: 'система' };
const STATUS = {
  risk: '<span class="chip c-risk">Грубая ошибка, нужна проверка</span>',
  review: '<span class="chip c-info">Нужна проверка человека</span>',
  next: '<span class="chip c-ev">Без следующего шага</span>',
  other: '',
};
const unfolded = new Set(); // ключи `${dialog}/${from}` раскрытых участков fold

const scored = cl => cl.criteria.filter(c => c.type !== 'flag');
const lineBy = (d, n) => (d.lines || []).find(l => !l.fold && l.n === n);
const current = () => (S.r && S.r.page === 'd' ? S.dialogs.find(d => d.id === S.r.id) : null);
const disagree = d => scored(S.checklist).filter(c => {
  const r = d.res[c.id];
  return r && r.alt != null && r.alt !== r.a && !lastDec(d, c.id, S.appeals);
});
const allowed = c => (c.type === 'bool' ? ['yes', 'no'] : [...c.steps]).concat(c.na ? ['na'] : []);

function tone(c, a) {
  if (a == null) return 'c-ev';
  if (a === 'na') return 'c-na';
  return frac(c, a) === 1 ? 'c-ok' : c.type === 'bool' ? 'c-risk' : 'c-ev';
}
const ptsTxt = (c, a) => { const f = frac(c, a); return f == null ? '—' : `${fn(c.w * f)} / ${c.w}`; };

function defaultOpen(d, sum) {
  const dc = disagree(d)[0];
  if (dc) return dc.id;
  if (sum.losses[0]) return sum.losses[0].c.id;
  const fc = S.checklist.criteria.find(c => c.type === 'flag');
  return flagsOf(d, S.checklist).length && fc ? fc.id : scored(S.checklist)[0]?.id;
}

export function view(S, id) {
  const d = S.dialogs.find(x => x.id === id);
  if (d && d.ch === 'call' && d.lines) player.mount(d);
  else player.unmount();
  if (!d) return `<div class="head"><div><h1 class="h1">Диалог не найден</h1>
    <p class="sub">Диалога «${esc(id)}» нет в загруженном наборе. <a href="#/queue">Вернуться к списку</a></p></div></div>`;
  const cl = S.checklist, call = d.ch === 'call';
  const sum = calc(d, cl, S.appeals);
  if (!(d.id in S.open)) S.open[d.id] = defaultOpen(d, sum);
  const open = S.open[d.id];
  const ord = queueOrder(S.dialogs, cl, S.appeals), i = ord.indexOf(d.id);
  const prev = ord[i - 1], next = ord[i + 1];
  const C = 2 * Math.PI * 52, dash = sum.total == null ? 0 : (C * sum.total) / 100;
  const naRows = scored(cl).filter(c => ans(d, c.id, S.appeals) === 'na');
  const flags = flagsOf(d, cl);
  const answered = scored(cl).filter(c => d.res[c.id] && d.res[c.id].alt != null).length;
  const fr = cl.criteria.find(c => c.type === 'flag'), frr = fr && d.res[fr.id];
  return `
  <nav class="row" aria-label="Навигация по очереди" style="justify-content:space-between">
    <a href="#/queue">Все диалоги</a>
    <div class="row small"><span class="muted">${i + 1} из ${ord.length} в очереди</span>
      ${prev ? `<a class="btn sm" href="${href('d', prev)}" aria-label="Предыдущий диалог">Предыдущий</a>` : ''}
      ${next ? `<a class="btn sm" href="${href('d', next)}" aria-label="Следующий диалог">Следующий</a>` : ''}</div>
  </nav>
  <div class="head">
    <div><h1 class="h1">${esc(titleOf(d))}</h1>
      <p class="sub">${call ? `Звонок, ${mmss(d.dur || 0)}` : 'Чат'}, ${esc(LANG[d.lang] || d.lang)}, ${esc(d.at)}, чек-лист v${cl.version}</p></div>
    <div class="row">${STATUS[groupOf(d, cl, S.appeals)]}${d.reviewed ? '<span class="chip c-ok">Проверен</span>' : ''}
      <button type="button" class="btn only-qa" data-act="reviewed">${d.reviewed ? 'Снять отметку' : 'Отметить проверенным'}</button></div>
  </div>

  <section class="sum" aria-label="Сводка">
    <div class="card pad stack">
      <h2 class="label">Итог</h2>
      <div class="ring">
        <svg width="124" height="124" viewBox="0 0 124 124" role="img" aria-label="Итог ${f2(sum.total)} из 100">
          <circle cx="62" cy="62" r="52" fill="none" stroke="#E2F1EB" stroke-width="11"/>
          <circle cx="62" cy="62" r="52" fill="none" stroke="#0E6A55" stroke-width="11" stroke-linecap="round" stroke-dasharray="${dash} ${C}" transform="rotate(-90 62 62)"/>
          <text x="62" y="66" text-anchor="middle" font-size="25" font-weight="700" fill="#17201C" font-family="Segoe UI, system-ui, sans-serif">${f2(sum.total)}</text>
          <text x="62" y="86" text-anchor="middle" font-size="12" fill="#56635D" font-family="Segoe UI, system-ui, sans-serif">из 100</text>
        </svg>
        <div class="secs">${sum.secs.map(s => `<div><span>${esc(s.name)}</span><b>${fn(s.g)} / ${s.w}</b></div>`).join('')}</div>
      </div>
      <details class="small"><summary style="cursor:pointer;color:var(--accent);font-weight:600">Как посчитан итог</summary>
        <p class="muted" style="margin-top:6px">${fn(sum.G)} балла из ${sum.W} применимых, приведено к 100.${naRows.length ? ` N/A у критериев ${naRows.map(x => x.id).join(', ')}: их вес распределён между остальными.` : ' N/A нет, веса не перераспределялись.'}${sum.pending ? ` Ждут оценки: ${sum.pending}, итог предварительный.` : ''}</p></details>
    </div>
    <div class="card pad stack">
      <h2 class="label">Почему снижена оценка</h2>
      ${sum.losses.length ? sum.losses.slice(0, 3).map((r, k) => {
        const rr = d.res[r.c.id] || {}, ln = rr.ev && rr.ev.length ? lineBy(d, rr.ev[0]) : null;
        return `<button type="button" class="loss" data-act="goto" data-cid="${esc(r.c.id)}"><span class="pinno">${k + 1}</span>
          <span><b>${esc(r.c.name)}</b>, ${esc(ansTxt(r.c, r.a))}<br><span class="muted small">${esc(rr.why)}</span>${ln ? `<br><span class="small" style="color:var(--accent)">Реплика ${ln.n}${call ? `, ${mmss(ln.t)}` : ''}</span>` : ''}</span>
          <em>−${fn(r.loss)}</em></button>`; }).join('') : '<p class="muted">Все применимые критерии выполнены полностью.</p>'}
      <p class="muted xs">${sum.losses.length > 3 ? `Ещё ${sum.losses.length - 3} в списке критериев. ` : ''}Потери посчитаны после перераспределения N/A и в сумме дают 100 − итог.</p>
    </div>
    <div class="card pad stack">
      <div class="row" style="justify-content:space-between"><h2 class="label">Грубые ошибки</h2>${flags.length ? `<span class="chip c-risk">Найдены: ${flags.length}</span>` : frr ? '<span class="chip c-ok">Не найдены</span>' : '<span class="chip c-ev">Ждут оценки</span>'}</div>
      ${fr ? (fr.questions || []).map(q => `<div class="kv"><span>${esc(q.label)}</span>${frr && frr.a[q.k] ? '<b style="color:var(--risk)">да</b>' : '<span class="muted">нет</span>'}</div>`).join('') : ''}
      ${flags.length && frr.ev && frr.ev.length ? `<button type="button" class="btn sm" data-act="goto" data-cid="${esc(fr.id)}">Показать реплику ${frr.ev.join(', ')}</button>` : ''}
      <p class="muted xs">Каждый вид проверяется отдельным вопросом. Флаг ставится, если нарушение нашла хотя бы одна из двух моделей. Итог он не обнуляет.</p>
      ${answered ? `<p class="small" style="margin-top:auto;border-top:1px solid var(--line2);padding-top:10px">Второе мнение совпало по ${answered - disagree(d).length} из ${answered} критериев</p>` : ''}
    </div>
  </section>

  ${call && d.lines ? player.html(d, sum.losses) : ''}

  <div class="cols">
    <section class="card" aria-label="Расшифровка">
      <div class="row" style="justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--line)">
        <h2 class="h2">${call ? 'Расшифровка звонка' : 'Переписка'}</h2>
        <span class="muted xs">${call ? 'Время от начала записи. ▶ ставит запись на начало реплики' : 'Время из чата, исходные метки сохранены'}</span>
      </div>
      <div class="tr" id="tr">${trHTML(d, open)}</div>
    </section>
    <section class="card" aria-label="Оценка по критериям">
      <div class="row" style="justify-content:space-between;padding:12px 14px">
        <h2 class="h2">Оценка по критериям</h2><span class="muted xs">Наведите на критерий, чтобы подсветить реплики</span></div>
      ${cl.sections.map((s, si) => {
        const cs = cl.criteria.filter(x => x.sec === si);
        if (!cs.length) return '';
        const sc = sum.secs.find(x => x.name === s);
        return `<div class="sechead"><span>${esc(s)}</span><span>${sc ? `${fn(sc.g)} / ${sc.w}` : ''}</span></div>${cs.map(c => critHTML(d, c, open)).join('')}`;
      }).join('')}
    </section>
  </div>`;
}

function trHTML(d, open) {
  if (!d.lines) return '<div class="empty">Расшифровка ещё не загружена. Оценка и обоснования — справа.</div>';
  const call = d.ch === 'call', tags = {};
  for (const c of S.checklist.criteria) {
    const r = d.res[c.id];
    if (!r || !r.ev) continue;
    const t = c.type === 'flag' ? (Object.values(r.a || {}).some(Boolean) ? 'c-risk' : 'c-ok') : tone(c, ans(d, c.id, S.appeals));
    r.ev.forEach(n => (tags[n] = tags[n] || []).push({ id: c.id, t }));
  }
  const sel = new Set((d.res[open] && d.res[open].ev) || []);
  const out = [];
  let hidden = null; // свёрнутый участок {from, to}: его реплики не выводятся
  for (const l of d.lines) {
    if (l.fold) {
      const key = `${d.id}/${l.from}`, shown = unfolded.has(key);
      hidden = shown ? null : l;
      out.push(`<div class="fold"><span>${call ? `${mmss(l.t0)}–${mmss(l.t1)}, ` : ''}<b>${esc(l.label)}</b>, реплики ${l.from}${l.to !== l.from ? '–' + l.to : ''}, не оценивается. <span class="muted">Модель видит участок как контекст.</span></span>
        <button type="button" class="btn sm" data-act="fold" data-key="${esc(key)}" aria-expanded="${shown}">${shown ? 'Свернуть' : 'Показать'}</button></div>`);
      continue;
    }
    if (hidden && l.n >= hidden.from && l.n <= hidden.to) continue;
    const tg = (tags[l.n] || []).map(x => `<button type="button" class="chip ${x.t}" data-act="crit" data-cid="${esc(x.id)}" aria-label="Открыть критерий ${esc(x.id)}">${esc(x.id)}</button>`).join(' ');
    const time = call ? mmss(l.t) : esc(l.t);
    const cls = sel.has(l.n) ? ' sel' : '';
    if (l.who === 'system' || l.who === 'bot') {
      out.push(`<div class="sys${cls}" id="L${l.n}" data-n="${l.n}">${l.n}, ${time}. ${l.who === 'bot' ? 'Бот' : 'Система'}: ${esc(l.text)} ${tg}</div>`);
      continue;
    }
    out.push(`<div class="msg ${l.who}${cls}" id="L${l.n}" data-n="${l.n}">
      <header><span>${l.n}</span><b>${l.who === 'client' ? 'Клиент' : 'Оператор'}</b><span>${time}</span>${call ? listen(d, l, true) : ''}${tg}</header>${esc(l.text)}</div>`);
  }
  return out.join('');
}

function critHTML(d, c, open) {
  const r = d.res[c.id], a = ans(d, c.id, S.appeals), isOpen = open === c.id;
  let chip, pts;
  if (c.type === 'flag') {
    const on = r && r.a && Object.values(r.a).some(Boolean);
    chip = !r ? '<span class="chip c-ev">ждёт оценки</span>' : on ? '<span class="chip c-risk">Да</span>' : '<span class="chip c-ok">Нет</span>';
    pts = 'без баллов';
  } else {
    chip = `<span class="chip ${tone(c, a)}">${esc(ansTxt(c, a))}</span>`;
    pts = ptsTxt(c, a);
  }
  return `<article class="crit${isOpen ? ' open' : ''}" data-cid="${esc(c.id)}" data-ev="${(r && r.ev || []).join(',')}">
    <button type="button" class="crit-row" data-act="crit" data-cid="${esc(c.id)}" aria-expanded="${isOpen}">
      <span class="muted small">${esc(c.id)}</span><span>${esc(c.name)}</span>${chip}<span class="num small" style="font-weight:600">${pts}</span>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>
    ${isOpen ? `<div class="crit-body">${critBody(d, c, r, a)}</div>` : ''}</article>`;
}

// Перемотка к началу реплики; без line.s — запасной путь на плеер организаторов в новой вкладке.
function listen(d, l, mini) {
  if (l.s == null) return `<a class="small" href="${esc(api.playerUrl(d.id))}" target="_blank" rel="noopener">Открыть в плеере</a>`;
  return mini
    ? `<button type="button" class="mini" data-act="seek" aria-label="Слушать реплику ${l.n} с ${mmss(l.s)}" title="Слушать с ${mmss(l.s)}">▶</button>`
    : `<button type="button" class="btn sm" data-act="seek" data-n="${l.n}">▶ Перейти к фрагменту, ${mmss(l.s)}</button>`;
}

function evidence(d, r) {
  return (r.ev || []).map(n => {
    const l = lineBy(d, n);
    if (!l) return '';
    return `<div class="quote"><div><span class="muted xs">${n}, ${WHO[l.who] || esc(l.who)}</span><br>«${esc(l.text)}»</div>
      <button type="button" class="btn sm" data-act="ev" data-n="${n}">К реплике</button>${d.ch === 'call' ? listen(d, l, false) : ''}</div>`;
  }).join('');
}

function critBody(d, c, r, a) {
  if (!r || a == null) return '<div class="box ev">Критерий ждёт оценки моделью. Пока итог считается без него.</div>';
  const evs = evidence(d, r);
  if (c.type === 'flag') {
    return `<div class="stack small">${(c.questions || []).map(q => `<div class="row" style="justify-content:space-between"><span>${esc(q.label)}</span>${r.a[q.k] ? '<b style="color:var(--risk)">найдено</b>' : '<span class="muted">нет</span>'}</div>`).join('')}</div>
      <p>${esc(r.why)}</p>${evs ? `<div class="stack"><span class="label">Основание</span>${evs}</div>` : ''}`;
  }
  const vals = allowed(c).filter(v => v !== 'na' || a === 'na' || r.alt === 'na');
  const altDiff = r.alt != null && r.alt !== a;
  let out = `<div class="stack" style="gap:6px"><div class="ladder" role="img" aria-label="Ответ ${esc(ansTxt(c, a))}${altDiff ? `, второе мнение ${esc(ansTxt(c, r.alt))}` : ''}">
    ${vals.map(v => `<span class="step${v === a ? ' on' : ''}${altDiff && v === r.alt ? ' alt' : ''}">${v === 'yes' ? 'Да' : v === 'no' ? 'Нет' : v === 'na' ? 'N/A' : v}</span>`).join('')}</div>
    ${c.type === 'scale' && c.stepText && c.stepText[a] ? `<span class="muted xs">${a}: ${esc(c.stepText[a])}</span>` : ''}</div>`;
  if (a === 'na') out += `<div class="box na"><b>Условие N/A выполнено.</b> ${esc(c.naCond)} ${esc(r.why)} Вес ${c.w} распределён между применимыми критериями.</div>`;
  else out += `<div><span class="label">Обоснование</span><p>${esc(r.why)}</p></div>`;
  if (a === 'no' && (r.seg || !(r.ev || []).length)) out += `<p class="small">Проверен участок: <b>${esc(r.seg || 'весь диалог')}</b>. Ожидаемого действия там нет.</p>`;
  if (evs) out += `<div class="stack" style="gap:6px"><span class="label">Основание</span>${evs}</div>`;
  const pa = S.appeals.find(x => x.dlg === d.id && x.cid === c.id && x.status === 'pending');
  out += pa ? `<p><span class="chip c-info">Апелляция на рассмотрении</span> <a href="${href('appeals', pa.id)}" class="small">Открыть</a></p>`
    : `<div class="no-rv"><button type="button" class="btn" data-act="appeal" data-cid="${esc(c.id)}">Оспорить оценку</button></div>`;
  return out;
}

function flashLine(n) {
  const el = document.getElementById('L' + n);
  if (!el) return;
  el.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  el.classList.remove('flash');
  void el.offsetWidth; // перезапуск анимации
  el.classList.add('flash');
}

export const actions = {
  ...player.actions,
  crit: t => { const id = S.r.id; S.open[id] = S.open[id] === t.dataset.cid ? null : t.dataset.cid; render(); },
  goto: t => {
    const d = current();
    S.open[d.id] = t.dataset.cid;
    render();
    const r = d.res[t.dataset.cid];
    const l = r && r.ev && r.ev.length ? lineBy(d, r.ev[0]) : null;
    if (!l) return;
    flashLine(l.n);
    if (l.s != null) player.seek(l.s, false);
  },
  pin: t => actions.goto(t),
  seek: t => {
    const l = lineBy(current(), Number(t.dataset.n || t.closest('[data-n]').dataset.n)); // ▶ в реплике — без своего data-n
    if (!l || l.s == null) return;
    player.seek(l.s);
    flashLine(l.n);
  },
  ev: t => flashLine(Number(t.dataset.n)),
  fold: t => { const k = t.dataset.key; unfolded.has(k) ? unfolded.delete(k) : unfolded.add(k); render(); },
};

// Наведение или фокус на критерии подсвечивает его реплики-основания.
if (typeof document !== 'undefined') {
  let hov = null;
  const hl = e => {
    const c = e.target.closest && e.target.closest('.crit');
    if (c === hov) return;
    hov = c;
    document.querySelectorAll('.tr .hl').forEach(x => x.classList.remove('hl'));
    if (c && c.dataset.ev) c.dataset.ev.split(',').filter(Boolean).forEach(n => document.getElementById('L' + n)?.classList.add('hl'));
  };
  document.addEventListener('mouseover', hl);
  document.addEventListener('focusin', hl);
}
