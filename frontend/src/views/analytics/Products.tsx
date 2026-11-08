// Вкладка «По продуктам» аналитики: GET /api/products/stats только при открытии вкладки (у сервера защиты его может не быть).
// Форма строки — как у OperatorRow: {id, name, dialogs, scored, avg_total, gross_errors, needs_review, weakest}.
import { f2 } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { href } from '../../lib/router.js';
import { Button, Card, Empty, Skeleton } from '../../ui';
import { Term } from '../../terms';
import { listOf, pct, useGet } from '../people/net';
import { Chart } from './Chart';

const nameOf = (r: any) => r.name ?? r.product ?? r.id ?? t('Не определён');

export function Products() {
  const st = useGet('/products/stats');
  const rows = listOf(st.data).length ? listOf(st.data) : listOf((st.data as any)?.products);
  if (st.loading) return <Skeleton className="h-60" />;
  if (st.error)
    return (
      <Card>
        <Empty action={<Button onClick={st.reload}>{t('Повторить')}</Button>}>{t('Статистика по продуктам недоступна: {error}', { error: st.error })}</Empty>
      </Card>
    );
  if (!rows.length)
    return (
      <Card>
        <Empty>{t('Продукты ещё не определены: они появятся после оценки набора.')}</Empty>
      </Card>
    );
  const scored = rows.filter((r: any) => r.avg_total != null);
  return (
    <>
      {scored.length > 0 && (
        <Chart
          title={t('Средний итог по продуктам')}
          caption={t('Средний итог оценённых диалогов каждого продукта с учётом решений.')}
          rows={scored.map((r: any) => ({ name: nameOf(r), value: r.avg_total, label: f2(r.avg_total), href: r.id ? href('queue', null, { product: r.id }) : undefined }))}
        />
      )}
      <Card aria-label={t('Качество по продуктам')}>
        <div className="px-4 pb-1.5 pt-4">
          <h2 className="text-base font-semibold">{t('Качество по продуктам')}</h2>
          <p className="text-[13px] text-muted">{t('Продукт диалога определяет модель по тексту; на карточке видно, почему, и его можно исправить.')}</p>
        </div>
        <div className="relative overflow-x-auto">
          <table className="tbl min-w-[720px]">
            <thead>
              <tr>
                <th>{t('Продукт')}</th>
                <th className="num">{t('Диалогов')}</th>
                <th className="num">{t('Оценено')}</th>
                <th className="num">{t('Средний итог')}</th>
                <th className="num">
                  <Term k="gross">{t('Грубые ошибки')}</Term>
                </th>
                <th className="num">{t('Нужна проверка')}</th>
                <th>{t('Слабые критерии')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={nameOf(r)} data-product={r.id ?? nameOf(r)}>
                  <td className="font-semibold">{r.id ? <a href={href('queue', null, { product: r.id })}>{nameOf(r)}</a> : nameOf(r)}</td>
                  <td className="num">{r.dialogs ?? '—'}</td>
                  <td className="num">{r.scored ?? '—'}</td>
                  <td className="num">{f2(r.avg_total)}</td>
                  {/* контракт: risk_share — доля диалогов с грубой ошибкой; gross_errors — прежняя форма (число) */}
                  <td className={`num ${r.gross_errors || r.risk_share ? 'font-semibold text-risk' : ''}`}>{r.gross_errors ?? (r.risk_share == null ? '—' : pct(r.risk_share))}</td>
                  <td className="num">{r.needs_review ?? '—'}</td>
                  <td className="text-[13px]">
                    {(r.weakest ?? []).map((w: any) => `${w.id ?? w.cid} ${w.name ?? ''} ${pct(w.share)}`).join('; ') || '—'}
                    {(r.reasons ?? []).length > 0 && (
                      <span className="mt-0.5 block text-xs text-muted">
                        {t('Причины: {list}', { list: r.reasons.map((x: any) => `${x.tag} (${x.dialogs})`).join(', ') })}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
