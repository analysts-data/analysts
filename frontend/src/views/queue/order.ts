// Видимые строки очереди (фильтры хеша и поиск S.q) и клавиатура: j/k/Enter/«/» в очереди, j/k в карточке.
import { titleOf } from '../../lib/format.js';
import { groupOf, queueOrder } from '../../lib/queue.js';
import { href, parseHash } from '../../lib/router.js';
import { ans, calc, frac } from '../../lib/scoring.js';
import { rerender, S } from '../../store';

export type Row = { d: any; c: any; g: string };

/** Строки очереди в порядке queueOrder после фильтров grp, lang, ch, lost и поиска S.q. */
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
    if (lost) {
      const f = frac(lost, ans(d, lost.id, ap));
      if (f == null || f >= 1) continue;
    }
    if (ql && !(titleOf(d) + ' ' + (d.lines || []).map((l: any) => l.text || '').join(' ')).toLowerCase().includes(ql)) continue;
    byId[d.id] = { d, c: calc(d, cl, ap), g };
  }
  return queueOrder(S.dialogs, cl, ap)
    .map((id: string) => byId[id])
    .filter(Boolean);
}

export const hasFilters = (p: Record<string, string>) => !!(p.grp || p.lang || p.ch || p.lost || S.q);

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
