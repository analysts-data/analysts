// Экран «Аналитика» (analytics-coaching, группа 3): каждое число открывает список диалогов, из него карточку и реплику.
import { criteriaStats, flagStats, nextStepStats, qualityStats, reasonsCsv, reasonsStats, resultsCsv } from '../analytics.js';
import { esc, fn, titleOf } from '../format.js';
import { href } from '../router.js';
import { twoModels } from '../queue.js';
import { S, api, render, toast } from '../state.js';

const LANGS = ['RU', 'KZ', 'EN'];
const OWNERS = ['Не назначено', 'Инструкция', 'Сервис', 'Продукт'];
const pct = x => x == null ? '—' : `${Math.round(100 * x)}%`;
const hcls = (k, n) => !n ? 'hm0' : k / n >= 0.6 ? 'hm4' : k / n >= 0.4 ? 'hm3' : k / n >= 0.2 ? 'hm2' : k ? 'hm1' : 'hm0';
const lost = (cid, lang) => esc(href('queue', null, { lost: cid, lang }));

function download(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function view(S) {
  const st = criteriaStats(S), fl = flagStats(S), q = qualityStats(S), rs = reasonsStats(S);
  const nextN = nextStepStats(S).dialogIds.length;
  const crit = id => S.checklist.criteria.find(c => c.id === id);
  const dlg = id => S.dialogs.find(d => d.id === id);
  // при равной доле остаётся критерий выше в чек-листе
  const dev = st.filter(x => x.n >= 3 && x.share != null).reduce((best, x) => (!best || x.share > best.share ? x : best), null);
  const top = rs.recurring[0];
  const maxR = top ? top.dialogs.length : 1;
  const flagged = fl.flaggedIds.length;
  const decidedAppeals = q.appeals.confirmed + q.appeals.changed;
  const cell = (x, lang) => {
    const b = x.byLang.find(l => l.lang === lang);
    return b ? `<a class="heat ${hcls(b.lost, b.n)}" style="text-decoration:none;color:inherit" href="${lost(x.cid, lang)}">${b.lost} из ${b.n}</a>` : '<div class="heat hm0">—</div>';
  };
  return `
  <div class="head"><div><h1 class="h1">Аналитика</h1><p class="sub">Каждое число открывает список диалогов, из него карточку и реплику</p></div>
    <span class="muted small">В наборе ${S.dialogs.length} диалогов. ${LANGS.map(l => `${l} ${S.dialogs.filter(d => d.lang === l).length}`).join(', ')}</span></div>
  <section class="lens" aria-label="Что получает бизнес">
    <a class="card" href="#/queue?grp=next"><span class="label">Качество сервиса</span><strong>${nextN}</strong><span>${nextN === 1 ? 'запрос остался' : 'запросов остались'} без решения или понятного следующего шага</span></a>
    <a class="card" href="#/queue?grp=risk"><span class="label">Контроль рисков</span><strong>${flagged}</strong><span>разговоров с грубыми ошибками, проверено ${fl.reviewed}</span></a>
    <a class="card" href="#/coaching"><span class="label">Развитие сотрудников</span><strong>${dev ? pct(dev.share) : '—'}</strong><span>${dev ? `применимых разговоров теряют баллы на критерии «${esc(dev.name)}»` : 'мало данных'}</span></a>
    <a class="card" href="#/analytics" data-act="toreasons"><span class="label">Улучшение процессов</span><strong>${top ? top.dialogs.length : 0}</strong><span>${top ? `разговоров с одной причиной: ${esc(top.tag.toLowerCase())}` : 'повторяющихся причин нет'}</span></a>
  </section>

  <section class="card" aria-label="Результат по критериям">
    <div class="pad" style="padding-bottom:6px"><h2 class="h2">Результат по критериям</h2>
      <p class="muted small">Доля считается среди применимых оценок, N/A показан отдельно. Где применимых меньше пяти, выводы ненадёжны.</p></div>
    <div class="tablewrap"><table style="min-width:820px"><thead><tr><th>Критерий</th><th class="num">Вес</th><th class="num">Применимо</th><th class="num">N/A</th><th class="num">Результат</th><th>Теряют баллы</th><th></th></tr></thead><tbody>
      ${st.map(x => `<tr class="click" data-act="lostrow" data-href="${lost(x.cid)}"><td><a href="${lost(x.cid)}" style="text-decoration:none;color:inherit"><span class="muted">${esc(x.cid)}</span> ${esc(x.name)}</a></td><td class="num">${fn(x.w)}</td><td class="num">${x.n}</td><td class="num">${x.na}</td>
        <td class="num">${x.val == null ? '—' : x.type === 'scale' ? `${fn(x.val)} из ${Math.max(...crit(x.cid).steps)}` : `${Math.round(x.val)}% «Да»`}</td>
        <td><span class="hbar" style="width:${x.share == null ? 0 : Math.max(2, 140 * x.share)}px"></span> <span class="small">${x.lost} из ${x.n}</span></td>
        <td>${x.pend ? `<span class="chip c-ev">ждёт оценки: ${x.pend}</span>` : x.n < 5 ? '<span class="chip c-na">мало данных</span>' : ''}</td></tr>`).join('')}
    </tbody></table></div>
  </section>

  <div class="two">
    <section class="card pad stack" aria-label="Критерий и язык">
      <div><h2 class="h2">Критерий и язык</h2><p class="muted small">Сколько применимых разговоров потеряли баллы. В ячейке число, а не только процент: на малых выборках процент обманчив.</p></div>
      <div class="tablewrap"><table><thead><tr><th>Критерий</th>${LANGS.map(l => `<th class="num">${l}</th>`).join('')}</tr></thead><tbody>
        ${st.map(x => `<tr class="click" data-act="lostrow" data-href="${lost(x.cid)}"><td title="${esc(crit(x.cid).text)}"><span class="muted">${esc(x.cid)}</span> ${esc(x.name)}</td>${LANGS.map(l => `<td style="width:84px;padding:4px" title="${esc(`${x.name}, ${l}: теряют баллы из применимых`)}">${cell(x, l)}</td>`).join('')}</tr>`).join('')}
      </tbody></table></div>
      <div class="row xs muted"><span>Светлее — реже теряют</span><span style="display:inline-flex;gap:2px"><i class="heat hm1" style="width:24px;min-height:12px"></i><i class="heat hm2" style="width:24px;min-height:12px"></i><i class="heat hm3" style="width:24px;min-height:12px"></i><i class="heat hm4" style="width:24px;min-height:12px"></i></span><span>темнее — чаще</span></div>
    </section>
    <section class="card pad stack" aria-label="Грубые ошибки и качество оценки">
      <div class="row" style="justify-content:space-between"><h2 class="h2">Грубые ошибки по видам</h2><a class="small" href="#/queue?grp=risk">Открыть ${flagged} в очереди</a></div>
      ${fl.kinds.map(k => `<div class="row" style="justify-content:space-between"><span>${esc(k.label)}</span><span><span class="hbar" style="background:var(--risk);width:${flagged ? (120 * k.n) / flagged : 0}px"></span> <b>${k.n}</b></span></div>`).join('')}
      <p class="muted xs">Флаг не входит в итог. Все такие разговоры стоят первыми в очереди, пока специалист их не проверит. Проверено ${fl.reviewed} из ${flagged}.</p>
      <h2 class="h2" style="margin-top:8px">Качество самой оценки</h2>
      <div class="grid2">
        ${twoModels(S) ? `<a href="#/queue?grp=review" style="text-decoration:none;color:inherit"><strong style="font-size:24px">${q.answers ? Math.round((100 * q.agree) / q.answers) : '—'}%</strong><p class="muted small">ответов двух моделей совпали (${q.agree} из ${q.answers}); оснований не нашлось: ${q.evFail}</p></a>`
    : `<a href="#/queue?grp=review" style="text-decoration:none;color:inherit"><strong style="font-size:24px">${q.evFail}</strong><p class="muted small">ответов без найденной в реплике цитаты; второе мнение выключено</p></a>`}
        <a href="#/queue?grp=review" style="text-decoration:none;color:inherit"><strong style="font-size:24px">${q.awaiting}</strong><p class="muted small">ответов ждут решения специалиста</p></a>
        <a href="#/appeals" style="text-decoration:none;color:inherit"><strong style="font-size:24px">${q.appeals.changed} из ${decidedAppeals}</strong><p class="muted small">решённых апелляций изменили оценку; ждут ${q.appeals.pending}, закрыто новой версией ${q.appeals.closed}</p></a>
        <div><strong style="font-size:24px">${q.reviews.changed} из ${q.reviews.confirmed + q.reviews.changed}</strong><p class="muted small">проверок расхождений изменили оценку модели</p></div>
      </div>
      <h3 class="label">Где модель расходится с людьми</h3>
      ${q.byCriterion.length ? `<div class="tablewrap"><table><thead><tr><th>Критерий</th><th>Язык</th><th class="num">Решено</th><th class="num">Изменено</th></tr></thead><tbody>
        ${q.byCriterion.map(x => `<tr class="click" data-act="lostrow" data-href="${lost(x.cid, x.lang)}"><td><span class="muted">${esc(x.cid)}</span> ${esc(crit(x.cid)?.name ?? '')}</td><td>${esc(x.lang)}</td><td class="num">${x.decided}</td><td class="num">${x.changed}</td></tr>`).join('')}
      </tbody></table></div>` : '<p class="muted small">Решений пока нет.</p>'}
      <p class="muted xs">Тренда по неделям нет: в данных нет дат.</p>
    </section>
  </div>

  <section class="card" id="reasons" aria-label="Повторяющиеся причины">
    <div class="pad row" style="justify-content:space-between;padding-bottom:6px"><div><h2 class="h2">Повторяющиеся причины</h2><p class="muted small">Причины снижения сгруппированы по точной формулировке. Кому их исправлять, решает человек.</p></div>
      <div class="row"><button type="button" class="btn sm" data-act="csv">Скачать CSV</button><button type="button" class="btn sm" data-act="resultscsv">Скачать итоги</button></div></div>
    <div class="tablewrap"><table style="min-width:820px"><thead><tr><th>Причина</th><th>Разговоров</th><th>Критерии</th><th>Языки</th><th>Что менять</th><th>Примеры</th></tr></thead><tbody>
      ${rs.recurring.map((g, k) => `<tr><td style="font-weight:600">${esc(g.tag)}</td><td><span class="hbar" style="width:${(80 * g.dialogs.length) / maxR}px"></span> <b>${g.dialogs.length}</b></td><td>${esc(g.criteria.join(', '))}</td><td>${esc(g.langs.join(', '))}</td>
        <td><label class="sr" for="own${k}">Что менять: ${esc(g.tag)}</label><select id="own${k}" class="fld" data-act="owner" data-tag="${esc(g.tag)}">${OWNERS.map(o => `<option ${g.owner === o ? 'selected' : ''}>${o}</option>`).join('')}</select></td>
        <td class="small">${g.dialogs.slice(0, 3).map(id => `<a href="${esc(href('d', id))}">${esc(titleOf(dlg(id)))}</a>`).join(', ')}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Повторяющихся причин нет.</td></tr>'}
    </tbody></table></div>
    ${rs.single ? `<p class="muted small pad">Ещё ${rs.single} причин встретились по одному разу. Они видны в карточках и в разделе «Обучение».</p>` : ''}
  </section>`;
}

export const actions = {
  lostrow: (t, e) => { if (!e.target.closest('a')) location.hash = t.dataset.href; },
  toreasons: (t, e) => { e.preventDefault(); document.getElementById('reasons').scrollIntoView({ block: 'start' }); },
  csv: () => download('cqa-reasons.csv', reasonsCsv(S)),
  resultscsv: () => download('cqa-results.csv', resultsCsv(S.dialogs, S.checklist, S.appeals)),
  // Без оптимистичного обновления: до ответа селектор заблокирован, при ошибке render вернёт прежнее значение.
  owner: async t => {
    t.disabled = true;
    try {
      S.owners = await api.putOwners({ [t.dataset.tag]: t.value });
    } catch (e) {
      toast(`Адресат не сохранён: ${e.message}`);
    }
    render();
  },
};
