// Видимые строки очереди (фильтры хеша и поиск S.q) и клавиатура: j/k/Enter/«/» в очереди, j/k в карточке.
import { titleOf } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { groupOf, queueOrder } from '../../lib/queue.js';
import { href, parseHash } from '../../lib/router.js';
import { ans, calc, frac } from '../../lib/scoring.js';
import { rerender, S } from '../../store';

export type Row = { d: any; c: any; g: string };

/** 1 диалог, 3 диалога, 5 диалогов. */
export const plural = (n: number, [one, few, many]: string[]) => {
  const a = n % 10,
    b = n % 100;
  return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many;
};
/** Формы слова для plural; функция — перевод t() при отрисовке. */
export const DIALOGS = () => [t('диалог'), t('диалога'), t('диалогов')];

// Сотрудник, продукт и маркеры приходят в /api/state по контракту; у старого сервера их нет — фильтры не показываются.
/** Диалоги без сотрудника — «Не указан», как у GET /api/report?operator=. */
export const NO_OPERATOR = 'Не указан';
export const operatorOf = (d: any): string => d.operator || NO_OPERATOR;
export const productOf = (d: any): { id: string; name: string } | null => (d.product?.id ? d.product : null);
export const markersOf = (d: any): { k: string; label: string; auto?: boolean; basis?: any }[] => (Array.isArray(d.markers) ? d.markers : []);

/** Все диалоги с расчётом и группой, без фильтров. */
export const rowsOf = (): Row[] => S.dialogs.map((d: any) => ({ d, c: calc(d, S.checklist, S.appeals), g: groupOf(d, S.checklist, S.appeals) }));

/** Строки очереди в порядке queueOrder после фильтров grp, lang, ch, lost, op, prod, mk и поиска S.q. */
export function visibleRows(p: Record<string, string>): Row[] {
  const cl = S.checklist,
    ap = S.appeals;
  const ql = S.q.trim().toLowerCase();
  const lost = p.lost ? cl.criteria.find((c: any) => c.id === p.lost) : null;
  const byId: Record<string, Row> = {};
  for (const d of S.dialogs) {
    const g = groupOf(d, cl, ap);
    if (p.grp && p.grp !== g) continue;
    if (p.lang && d.lang !== p.lang) continue;
    if (p.ch && d.ch !== p.ch) continue;
    if (p.op && operatorOf(d) !== p.op) continue;
    if (p.prod && productOf(d)?.id !== p.prod) continue;
    if (p.mk && !markersOf(d).some(m => m.k === p.mk)) continue;
    if (lost) {
      const f = frac(lost, ans(d, lost.id, ap));
      if (f == null || f >= 1) continue;
    }
    if (ql && !(titleOf(d) + ' ' + (d.lines || []).map((l: any) => l.text || '').join(' ')).toLowerCase().includes(ql)) continue;
    byId[d.id] = { d, c: calc(d, cl, ap), g };
  }
  const rows: Row[] = queueOrder(S.dialogs, cl, ap)
    .map((id: string) => byId[id])
    .filter(Boolean);
  if (S.role !== 'operator') return rows;
  // оператору «Нужна проверка человека» не показывается: эти строки идут в «Остальные»
  const rank: Record<string, number> = { risk: 0, next: 1 };
  return rows.sort((a, b) => (rank[a.g] ?? 2) - (rank[b.g] ?? 2));
}

export const hasFilters = (p: Record<string, string>) => !!(p.grp || p.lang || p.ch || p.lost || p.op || p.prod || p.mk || S.q);

const typing = (t: EventTarget | null) => (t as Element | null)?.closest?.('input,textarea,select,[contenteditable="true"],[role="dialog"]');

// Слушатель на документе: карточка (не наш экран) тоже листает очередь клавишами j/k.
document.addEventListener('keydown', e => {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
  const down = e.key === 'j' || e.key === 'о',
    up = e.key === 'k' || e.key === 'л';
  if (!down && !up && e.key !== 'Enter' && e.key !== '/') return;
  if (!S.checklist || !S.dialogs?.length) return;
  // Хеш напрямую: быстрый повтор до hashchange не должен видеть прошлый маршрут.
  const { page, id, params } = parseHash(location.hash);
  if (page === 'd') {
    if (!down && !up) return;
    const ord = queueOrder(S.dialogs, S.checklist, S.appeals);
    const n = ord[ord.indexOf(id) + (down ? 1 : -1)];
    if (n) location.hash = href('d', n);
    return;
  }
  if (page !== 'queue') return;
  if (e.key === '/') {
    e.preventDefault();
    document.getElementById('q')?.focus();
    return;
  }
  const ids = visibleRows(params).map(x => x.d.id);
  if (!ids.length) return;
  const i = ids.indexOf(S.qsel);
  if (down || up) {
    // Первое нажатие выделяет первую строку.
    S.qsel = ids[i < 0 ? 0 : Math.min(ids.length - 1, Math.max(0, i + (down ? 1 : -1)))];
    rerender();
    requestAnimationFrame(() => document.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' }));
  } else if (e.key === 'Enter' && i >= 0 && !(e.target as Element).closest?.('a,button')) {
    location.hash = href('d', S.qsel);
  }
});
