// Группы очереди прототипа: грубые ошибки → нужна проверка → без следующего шага → остальные. Без DOM.
import { ans, calc, flagsOf, frac, lastDec } from './scoring.js';
import { ansTxt } from './format.js';

const scored = checklist => checklist.criteria.filter(c => c.type !== 'flag');
const open = (d, appeals, pick) => c => { const r = d.res[c.id]; return r && pick(r) && !lastDec(d, c.id, appeals); };
const disagree = (d, cl, ap) => scored(cl).filter(open(d, ap, r => r.alt != null && r.alt !== r.a));
const evFail = (d, cl, ap) => scored(cl).filter(open(d, ap, r => r.evFail));
const resolution = cl => scored(cl).find(c => c.signal === 'resolution');
// Ответ режима «только Jev» (или mode этого режима): model — JEV_MODEL из src/cqa/adapters/jev.py.
export const byJev = r => /^jev/.test(r?.model || '');
// Подписи про две модели: второе мнение включено или уже есть в ответах (режим могли сменить после оценки).
export const twoModels = S => S.mode?.verifier != null || S.dialogs.some(d => Object.values(d.res).some(r => r.alt != null));

export function groupOf(d, checklist, appeals) {
  if (!d.reviewed && flagsOf(d, checklist, appeals).length) return 'risk';
  if (!d.reviewed && (disagree(d, checklist, appeals).length || evFail(d, checklist, appeals).length)) return 'review';
  const nextStep = scored(checklist).some(c => {
    if (c.signal !== 'resolution') return false;
    const f = frac(c, ans(d, c.id, appeals));
    return f != null && f < 1; // любая ступень ниже верхней: «передам специалистам» без срока — 15 из 20
  });
  return nextStep ? 'next' : 'other';
}

const GORDER = { risk: 0, review: 1, next: 2, other: 3 };

// Идентификаторы в порядке очереди: по группам, внутри по итогу по возрастанию, диалог без итога — первым.
export const queueOrder = (dialogs, checklist, appeals) => dialogs
  .map(d => ({ id: d.id, g: GORDER[groupOf(d, checklist, appeals)], t: calc(d, checklist, appeals).total ?? -1 }))
  .sort((x, y) => x.g - y.g || x.t - y.t)
  .map(x => x.id);

// Колонка «Почему в очереди»: {cls, text} для чипа.
export function reasonOf(d, checklist, appeals) {
  const g = groupOf(d, checklist, appeals);
  if (g === 'risk') return { cls: 'c-risk', text: flagsOf(d, checklist, appeals).join(', ') };
  if (g === 'review') {
    const dc = disagree(d, checklist, appeals)[0];
    if (dc) { const r = d.res[dc.id]; return { cls: 'c-info', text: `Модели разошлись: ${dc.id}, ${ansTxt(dc, r.a)} и ${ansTxt(dc, r.alt)}` }; }
    const ef = evFail(d, checklist, appeals)[0];
    return { cls: 'c-ev', text: byJev(d.res[ef.id]) ? `Jev не уверен в ответе: ${ef.id}` : `Цитата для ${ef.id} не найдена в реплике` };
  }
  if (g === 'next') { const c = resolution(checklist); return { cls: 'c-ev', text: `${c.name}: ${ansTxt(c, ans(d, c.id, appeals))}` }; }
  return flagsOf(d, checklist, appeals).length ? { cls: 'c-na', text: 'Грубая ошибка проверена' } : { cls: '', text: '' };
}

// Строка автосинхронизации из state.source; ссылку сервер не отдаёт.
export function syncNote(s) {
  if (!s) return '';
  const head = `Автосинхронизация ${s.group_id} раз в 5 минут`;
  if (!s.synced_at) return head;
  const time = new Date(s.synced_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  return `${head}, последняя в ${time}: ${s.error ? `ошибка — ${s.error}` : `добавлено ${s.added}`}`;
}
