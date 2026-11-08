// Вкладка «Прогоны» аналитики: журнал запусков оценки (GET /api/runs) и сравнение двух (GET /api/runs/compare?a=&b=).
// Запросы — только при открытии вкладки и по кнопке «Сравнить»: у сервера защиты этих путей может не быть.
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { ansTxt, fn, titleOf } from '../../lib/format.js';
import { href } from '../../lib/router.js';
import { t } from '../../lib/i18n.js';
import { api } from '../../lib/state.js';
import { useS } from '../../store';
import { Button, Card, Chip, Empty, Skeleton, Tip } from '../../ui';
import { apiUrl, listOf, pct, useGet, when } from '../people/net';
import { Chart } from './Chart';

const status = (): Record<string, [string, 'ok' | 'info' | 'na' | 'risk']> => ({ done: [t('готов'), 'ok'], running: [t('оценивается…'), 'info'], cancelled: [t('остановлен'), 'na'] });

export function Runs() {
  const S = useS();
  const runs = useGet('/runs');
  const list = listOf(runs.data);
  const [pick, setPick] = useState<{ a?: string; b?: string }>({});
  const a = pick.a ?? String(list[1]?.id ?? '');
  const b = pick.b ?? String(list[0]?.id ?? '');
  const [cmp, setCmp] = useState<{ busy: boolean; data: any; error: string | null }>({ busy: false, data: null, error: null });
  const crit = (cid: string) => S.checklist?.criteria.find((c: any) => c.id === cid);
  const why = list.length < 2 ? t('Нужно хотя бы два прогона: оцените набор заново.') : a === b ? t('Выберите два разных прогона.') : null;

  async function compare() {
    setCmp({ busy: true, data: null, error: null });
    try {
      setCmp({ busy: false, data: await api.get(`/runs/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`), error: null });
    } catch (e) {
      setCmp({ busy: false, data: null, error: e.message });
    }
  }

  if (runs.loading) return <Skeleton className="h-60" />;
  if (runs.error)
    return (
      <Card>
        <Empty action={<Button onClick={runs.reload}>{t('Повторить')}</Button>}>{t('Журнал прогонов недоступен: {error}', { error: runs.error })}</Empty>
      </Card>
    );
  if (!list.length)
    return (
      <Card>
        <Empty action={<a href="#/queue">{t('Перейти к диалогам')}</a>}>{t('Прогонов ещё не было.')}</Empty>
      </Card>
    );
  const c = cmp.data;
  return (
    <>
      <Card aria-label={t('Журнал прогонов')}>
        <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-1.5 pt-4">
          <div>
            <h2 className="text-base font-semibold">{t('Журнал прогонов')}</h2>
            <p className="text-[13px] text-muted">{t('Каждый запуск оценки хранит свои ответы. Отметьте А и Б, чтобы сравнить два прогона или две модели на одном наборе.')}</p>
          </div>
          <div className="flex items-center gap-2.5">
            {why && <span className="text-[13px] text-muted">{why}</span>}
            <Button variant="primary" size="sm" data-act="compare" disabled={!!why || cmp.busy} onClick={compare}>
              {cmp.busy ? t('Сравнивается…') : t('Сравнить')}
            </Button>
          </div>
        </div>
        <div className="relative overflow-x-auto">
          <table className="tbl min-w-[860px]">
            <thead>
              <tr>
                <th>{t('А')}</th>
                <th>{t('Б')}</th>
                <th>{t('Прогон')}</th>
                <th>{t('Модель')}</th>
                <th className="num">{t('Чек-лист')}</th>
                <th className="num">{t('Ответов')}</th>
                <th className="num">{t('Пропущено')}</th>
                <th className="num">{t('Ошибки')}</th>
                <th className="num">{t('Цена')}</th>
                <th>{t('Статус')}</th>
                <th>
                  <span className="sr">{t('Отчёт')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((r: any) => {
                const id = String(r.id);
                const [st, tone] = status()[r.status] ?? [r.status, 'na'];
                return (
                  <tr key={id} data-run={id} className={a === id || b === id ? 'sel' : undefined}>
                    <td>
                      <input type="radio" name="run-a" aria-label={t('Прогон {id} как А', { id })} checked={a === id} onChange={() => setPick({ a: id, b })} />
                    </td>
                    <td>
                      <input type="radio" name="run-b" aria-label={t('Прогон {id} как Б', { id })} checked={b === id} onChange={() => setPick({ a, b: id })} />
                    </td>
                    <td className="whitespace-nowrap">
                      {t('№ {id}', { id })} <span className="text-muted">{when(r.created)}</span>
                      {r.force && (
                        <Tip content={t('Оценка заново: ручные ответы и решения людей не перезаписаны, такие пары пропущены.')}>
                          <span tabIndex={0}>
                            <Chip tone="info" className="ml-2">
                              {t('заново')}
                            </Chip>
                          </span>
                        </Tip>
                      )}
                    </td>
                    <td>{r.model ?? '—'}</td>
                    <td className="num">{r.checklist_version ? `v${r.checklist_version}` : '—'}</td>
                    <td className="num">
                      {t('{done} из {total}', { done: r.done, total: r.total })}
                    </td>
                    <td className="num">{r.skipped ?? 0}</td>
                    <td className={`num ${r.errors_count ? 'text-risk' : ''}`}>{r.errors_count ?? 0}</td>
                    <td className="num">{r.cost == null ? '—' : `$${fn(r.cost)}`}</td>
                    <td>
                      <Chip tone={tone}>{st}</Chip>
                    </td>
                    <td>
                      <a href={apiUrl(`/runs/${encodeURIComponent(id)}/report?format=html`)} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-[13px] no-underline">
                        {t('Отчёт')} <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {cmp.error && (
        <div className="box risk" role="alert">
          {t('Сравнение не получено: {error}', { error: cmp.error })}
        </div>
      )}
      {c && (
        <>
          <Card aria-label={t('Сравнение прогонов')} className="flex flex-col gap-1 px-4 py-4">
            <h2 className="text-base font-semibold">
              {t('Прогон № {a} и № {b}', { a: c.a, b: c.b })}
            </h2>
            <p className="text-[13px] text-muted">
              {t('Общих пар «диалог, критерий»: {n}. Совпадение ответов:', { n: c.pairs })} <b className="text-ink">{pct(c.agree)}</b>. {t('Решения проверяющих в сравнении не участвуют.')}
            </p>
          </Card>
          {c.criteria?.length > 0 && (
            <Chart
              title={t('Совпадение по критериям')}
              caption={t('Доля пар, где оба прогона ответили одинаково.')}
              rows={c.criteria
                .filter((x: any) => x.agree != null)
                .map((x: any) => ({ name: `${x.cid} ${crit(x.cid)?.name ?? ''}`.trim(), value: Math.round(100 * x.agree), label: x.mean_step_diff ? t('{p} из {n}, ±{d} ступ.', { p: pct(x.agree), n: x.pairs, d: fn(x.mean_step_diff) }) : t('{p} из {n}', { p: pct(x.agree), n: x.pairs }) }))}
            />
          )}
          <Card aria-label={t('Расхождения')}>
            <div className="px-4 pb-1.5 pt-4">
              <h2 className="text-base font-semibold">{t('Расхождения')}</h2>
              <p className="text-[13px] text-muted">{t('Пары, где прогоны ответили по-разному. Диалог открывает карточку и историю оценок.')}</p>
            </div>
            {c.diffs?.length ? (
              <div className="relative overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>{t('Диалог')}</th>
                      <th>{t('Критерий')}</th>
                      <th>{t('Ответ А')}</th>
                      <th>{t('Ответ Б')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.diffs.map((x: any) => {
                      const cr = crit(x.cid);
                      const d = S.dialogs.find((y: any) => y.id === x.dialog);
                      return (
                        <tr key={`${x.dialog}|${x.cid}`}>
                          <td>
                            <a href={href('d', x.dialog)}>{d ? titleOf(d) : x.dialog}</a>
                          </td>
                          <td>
                            <span className="text-muted">{x.cid}</span> {cr?.name ?? ''}
                          </td>
                          <td>{cr ? ansTxt(cr, x.a) : JSON.stringify(x.a)}</td>
                          <td>{cr ? ansTxt(cr, x.b) : JSON.stringify(x.b)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="px-4 pb-4 text-[13px] text-muted">{t('Расхождений нет.')}</p>
            )}
          </Card>
        </>
      )}
    </>
  );
}
