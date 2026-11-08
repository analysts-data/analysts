// Формат обмена — значение questions запроса Jev, без настроек подсчёта баллов.
import { t } from './i18n.js';

const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const fail = (id, message) => { throw new Error(`${id}: ${message}`); };

function parseQuestion(id, q) {
  if (!object(q) || !['noul', 'choice', 'score'].includes(q.type)) fail(id, t('ожидается тип noul, choice или score'));
  if (typeof q.instructions !== 'string' || !q.instructions.trim()) fail(id, t('instructions должен содержать текст'));
  const source = { type: q.type, instructions: q.instructions, criteria: structuredClone(q.criteria) };
  const c = { id, name: id, type: 'bool', w: 0, na: false, text: q.instructions, channel: 'all' };
  if (q.type === 'score') {
    if (!Array.isArray(q.criteria) || !q.criteria.length) fail(id, t('criteria шкалы должен быть непустым массивом строк'));
    const steps = new Map();
    for (const line of q.criteria) {
      const m = typeof line === 'string' && line.match(/^\s*(\d+|n\/a|na|not_applicable)\s*:\s*(.+)$/i);
      if (!m) fail(id, t('ступень должна иметь вид «0: описание» или «n/a: условие»'));
      if (/^\d+$/.test(m[1])) {
        const n = Number(m[1]);
        if (!Number.isSafeInteger(n) || steps.has(n)) fail(id, t('некорректная или повторная ступень шкалы'));
        steps.set(n, m[2]);
      } else {
        if (c.na) fail(id, t('повторное условие N/A'));
        c.na = true; c.naCond = m[2];
      }
    }
    if (steps.size < 2 || Math.max(...steps.keys()) <= 0) fail(id, t('нужны хотя бы две ступени и положительный максимум'));
    c.type = 'scale'; c.steps = [...steps.keys()].sort((a, b) => b - a); c.stepText = Object.fromEntries(steps);
    for (const k of ['min', 'max']) {
      if (q[k] !== undefined) {
        if (!Number.isSafeInteger(q[k]) || q[k] < 0) fail(id, t('{k} должен быть неотрицательным целым числом', { k }));
        source[k] = q[k];
      }
    }
    if ((source.min !== undefined && source.min !== Math.min(...c.steps)) ||
        (source.max !== undefined && source.max !== Math.max(...c.steps))) fail(id, t('min/max должны совпадать с границами ступеней'));
  } else {
    if (!object(q.criteria) || Object.values(q.criteria).some(v => typeof v !== 'string' || !v.trim())) fail(id, t('criteria должен содержать текстовые описания ответов'));
    const keys = Object.keys(q.criteria), required = q.type === 'noul' ? ['true', 'false'] : ['yes', 'no'];
    if (required.some(k => !keys.includes(k)) || keys.some(k => !required.includes(k) && !(q.type === 'choice' && ['na', 'not_applicable'].includes(k)))) fail(id, t('неподдерживаемые варианты ответа'));
    if (keys.includes('na') && keys.includes('not_applicable')) fail(id, t('используйте только один ключ N/A'));
    c.naCond = q.criteria.not_applicable ?? q.criteria.na ?? null;
    c.na = c.naCond !== null;
  }
  c.jev = source;
  return c;
}

export function importQuestions(draft, input) {
  const questions = object(input) && object(input.questions) ? input.questions : input;
  if (!object(questions) || !Object.keys(questions).length) throw new Error(t('Ожидается непустой объект questions'));
  // Сначала проверяем весь файл: ошибка не должна оставлять частично загруженный черновик.
  const parsed = Object.entries(questions).map(([id, q]) => {
    if (!id.trim()) fail(id, t('пустой ID'));
    return parseQuestion(id, q);
  });
  const result = structuredClone(draft);
  if (!result.sections.length) result.sections.push('Импортированные проверки');
  let added = 0, updated = 0;
  for (const c of parsed) {
    const index = result.criteria.findIndex(x => x.id === c.id);
    if (index < 0) {
      result.criteria.push({ ...c, sec: 0 }); added++;
    } else {
      const old = result.criteria[index];
      result.criteria[index] = { ...c, sec: old.sec, name: old.name, w: old.w, channel: old.channel || 'all', ...(old.signal ? { signal: old.signal } : {}), ...(old.call ? { call: old.call } : {}) };
      if (result.criteria[index].channel !== 'all' && !c.na) fail(c.id, t('сохранённый канал требует N/A; выберите «Все каналы» перед импортом'));
      updated++;
    }
  }
  return { draft: result, added, updated };
}

export function syncJev(c, field) {
  if (!c.jev) return;
  if (field === 'text') { c.jev.instructions = c.text; return; }
  if (!['type', 'steps', 'na', 'naCond'].includes(field)) return;
  const old = c.jev;
  if (c.type === 'flag') { delete c.jev; return; }
  if (c.type === 'scale') {
    c.jev = { type: 'score', instructions: c.text, min: Math.min(...c.steps), max: Math.max(...c.steps),
      criteria: [...c.steps.map(s => `${s}: ${c.stepText?.[s] || ''}`), ...(c.na ? [`n/a: ${c.naCond || 'Неприменимо'}`] : [])] };
  } else {
    const source = object(old.criteria) ? old.criteria : {};
    const noul = old.type === 'noul' && !c.na;
    const criteria = noul
      ? { true: source.true ?? source.yes ?? 'Да', false: source.false ?? source.no ?? 'Нет' }
      : { yes: source.yes ?? source.true ?? 'Да', no: source.no ?? source.false ?? 'Нет',
          ...(c.na ? { [Object.hasOwn(source, 'not_applicable') ? 'not_applicable' : 'na']: c.naCond || 'Неприменимо' } : {}) };
    c.jev = { type: noul ? 'noul' : 'choice', instructions: c.text, criteria };
  }
}

export function exportQuestions(draft) {
  const entries = [];
  for (const c of draft.criteria) {
    if (c.type === 'flag') {
      for (const q of c.questions || []) entries.push([`${c.id}_${q.k}`, { type: 'noul', instructions: q.text || q.label,
        criteria: { true: 'Нарушение выявлено', false: 'Нарушение не выявлено' } }]);
    } else {
      const copy = structuredClone(c);
      if (!copy.jev) { copy.jev = { type: 'choice', criteria: {} }; syncJev(copy, 'type'); }
      entries.push([c.id, { ...copy.jev, instructions: c.text }]);
    }
  }
  if (new Set(entries.map(([id]) => id)).size !== entries.length) throw new Error(t('Совпадают ID экспортируемых вопросов'));
  return Object.fromEntries(entries);
}
