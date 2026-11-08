// Экранирование и форматы прототипа. Транскрипт и ответы модели — данные: каждая вставка в HTML идёт через esc.
import { lang, t } from './i18n.js';

// Тег локали чисел и дат по языку интерфейса; русский — по умолчанию.
export const loc = () => ({ ru: 'ru-RU', en: 'en-US', kk: 'kk-KZ' })[lang] || 'ru-RU';

const HTML = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => HTML[c]);
export const titleOf = d => d.title || d.id;
export const f2 = x => x == null ? '—' : x.toLocaleString(loc(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fn = x => (Math.round(x * 100) / 100).toLocaleString(loc(), { maximumFractionDigits: 2 });
export const mmss = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
export const ansTxt = (c, a) => a == null ? t('ждёт оценки') : a === 'na' ? 'N/A' : a === 'yes' ? t('Да') : a === 'no' ? t('Нет')
  : c.type === 'scale' ? t('{a} из {max}', { a, max: Math.max(...c.steps) })
  : c.type === 'flag' ? (c.questions || []).filter(q => a[q.k]).map(q => q.label).join(', ') || t('Нарушений нет') : String(a);
