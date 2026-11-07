// Апелляция из карточки и отметка «проверен». Чистые функции наверху, DOM только внутри действий.
import { S, api, reload, toast } from './state.js';
import { ans } from './scoring.js';
import { esc, titleOf, ansTxt } from './format.js';

// Допустимые ответы критерия: ступени шкалы или да/нет, N/A — только где разрешён.
export const allowed = c => [...(c.type === 'scale' ? c.steps : ['yes', 'no']), ...(c.na ? ['na'] : [])];

// Подпись текущей роли в полях by и reviewer.
const SIGN = { qa: 'Специалист КК', operator: 'Оператор', reviewer: 'Проверяющий' };
export const signOf = role => SIGN[role];

// Значение из атрибута или поля формы: ступень шкалы — число, остальное — строка.
export const answerOf = v => (/^\d+$/.test(v) ? Number(v) : v);

const MIN_COMMENT = 10;
const current = () => S.dialogs.find(d => d.id === S.r.id);
const crit = cid => S.checklist.criteria.find(c => c.id === cid);
const pending = (d, cid) => S.appeals.some(a => a.dlg === d.id && a.cid === cid && a.status === 'pending');

// Сейчас: ответ с учётом решений и обоснование; варианты — допустимые без текущего.
function choice(d, cid) {
  const c = crit(cid), a = ans(d, cid, S.appeals);
  return {
    now: `Сейчас: <b>${esc(ansTxt(c, a))}</b>. ${esc(d.res[cid].why || '')}`,
    opts: allowed(c).filter(v => v !== a).map(v => `<option value="${esc(v)}">${esc(ansTxt(c, v))}</option>`).join(''),
  };
}

export function openAppeal(d, cid) {
  const cs = S.checklist.criteria.filter(c => c.type !== 'flag' && d.res[c.id] && !pending(d, c.id));
  const ch = choice(d, cid);
  const lines = (d.lines || []).filter(l => !l.fold && l.who !== 'system');
  const form = S.app.querySelector('#dlgForm');
  form.innerHTML = `<header><h2 class="h2" id="dlgTitle">Оспорить оценку</h2><p class="muted small">${esc(titleOf(d))}, подаёт: ${esc(signOf(S.role))}</p></header>
    <label class="field"><span>Критерий</span><select name="cid" class="fld" data-act="acid">${cs.map(c => `<option value="${esc(c.id)}" ${c.id === cid ? 'selected' : ''}>${esc(c.id)} ${esc(c.name)}</option>`).join('')}</select></label>
    <p class="box na" id="aNow">${ch.now}</p>
    <label class="field"><span>Какой ответ вы считаете верным</span><select name="ask" class="fld" id="aAsk">${ch.opts}</select></label>
    <label class="field"><span>Комментарий, обязательно</span><textarea name="comment" class="fld" data-act="acomment" placeholder="Почему оценка неверна, со ссылкой на реплику, не короче ${MIN_COMMENT} символов"></textarea></label>
    ${lines.length ? `<label class="field"><span>Реплика в подтверждение</span><select name="ev" class="fld"><option value="">Не выбрана</option>${lines.map(l => `<option value="${l.n}">${l.n}: ${esc(l.text.slice(0, 60))}${l.text.length > 60 ? '…' : ''}</option>`).join('')}</select></label>` : ''}
    <p class="box risk" id="aErr" role="alert" hidden></p>
    <p class="muted small">Апелляцию рассмотрит проверяющий. Исходная оценка сохранится, решение и новый итог появятся в карточке рядом с ней.</p>
    <footer><button class="btn" value="cancel" formnovalidate>Отмена</button><button type="button" class="btn pri" data-act="asend" disabled>Отправить апелляцию</button></footer>`;
  form.closest('dialog').showModal();
}

export const actions = {
  appeal: t => openAppeal(current(), t.dataset.cid),
  acid: t => {
    const ch = choice(current(), t.value);
    t.form.querySelector('#aNow').innerHTML = ch.now;
    t.form.querySelector('#aAsk').innerHTML = ch.opts;
  },
  acomment: t => { t.form.querySelector('[data-act="asend"]').disabled = t.value.trim().length < MIN_COMMENT; },
  asend: async t => {
    const f = t.form, d = current(), cid = f.elements.cid.value, ev = f.elements.ev?.value;
    const err = f.querySelector('#aErr');
    t.disabled = true;
    try {
      await api.postAppeal({
        dlg: d.id, cid, ask: answerOf(f.elements.ask.value), ev: ev ? [Number(ev)] : [],
        comment: f.elements.comment.value.trim(), by: signOf(S.role),
      });
    } catch (e) {
      err.textContent = `Апелляция не отправлена: ${e.message}`;
      err.hidden = false;
      t.disabled = false;
      return;
    }
    f.closest('dialog').close();
    await reload();
    toast(`Апелляция по критерию «${crit(cid).name}» отправлена проверяющему.`);
  },
  reviewed: async t => {
    const d = current(), on = !d.reviewed;
    t.disabled = true;
    try {
      await api.postReviewed(d.id, on);
    } catch (e) {
      t.disabled = false;
      toast(`Отметка не сохранена: ${e.message}`);
      return;
    }
    await reload();
    toast(on ? `${titleOf(d)} отмечен проверенным и уходит из верхних групп очереди.` : 'Отметка снята, диалог вернулся в очередь.');
  },
};
