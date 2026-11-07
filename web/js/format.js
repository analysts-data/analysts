// Экранирование и форматы прототипа. Транскрипт и ответы модели — данные: каждая вставка в HTML идёт через esc.
const HTML = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => HTML[c]);
export const titleOf = d => d.title || d.id;
export const f2 = x => x == null ? '—' : x.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fn = x => (Math.round(x * 100) / 100).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
export const mmss = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
export const ansTxt = (c, a) => a == null ? 'ждёт оценки' : a === 'na' ? 'N/A' : a === 'yes' ? 'Да' : a === 'no' ? 'Нет'
  : c.type === 'scale' ? `${a} из ${Math.max(...c.steps)}` : String(a);
