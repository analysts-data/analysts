// «Журнал действий»: кто, когда, что и над чем сделал (GET /api/audit). Фильтры живут в адресе (#/audit?actor=e1),
// поэтому ссылка со страницы сотрудника открывает его действия. CSV — тот же запрос с format=csv.
import { Download } from 'lucide-react';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { go, useRoute, useS } from '../store';
import { Button, Card, Empty, Field, PageHead, Skeleton, Tip } from '../ui';
import { actionName, actionNames, DownloadButton, listOf, roleName, useGet, when } from './people/net';

const PAGE = 100;
const FILTERS = ['actor', 'action', 'since'] as const;

const targetNames = (): Record<string, string> => ({ dialog: t('диалог'), appeal: t('апелляция'), checklist: t('чек-лист'), employee: t('сотрудник'), run: t('оценка'), alert: t('алерт'), set: t('набор') });

/** Ссылка на объект действия: диалог, апелляция, чек-лист, сотрудник; остальное — текстом. */
function Target({ type, id }: { type: string; id: string }) {
  const to = type === 'dialog' ? href('d', id) : type === 'appeal' ? href('appeals', id) : type === 'checklist' ? '#/checklist' : type === 'employee' ? href('people', id) : null;
  const text = `${targetNames()[type] ?? type ?? ''} ${id ?? ''}`.trim();
  return to ? <a href={to}>{text}</a> : <span>{text || '—'}</span>;
}

const detailsText = (d: any) =>
  d && typeof d === 'object'
    ? Object.entries(d)
        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join('; ')
    : String(d ?? '');

export function Audit({ id }: { id: string | null }) {
  const S = useS();
  const { params } = useRoute();
  const f = Object.fromEntries(FILTERS.map(k => [k, params[k] ?? '']));
  const limit = Number(params.limit) || PAGE;
  const query = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const log = useGet(`/audit?${query ? query + '&' : ''}limit=${limit}`);
  const rows = listOf(log.data);
  const set = (k: string, v: string) => go(href('audit', null, { ...f, [k]: v }));

  return (
    <>
      <PageHead title={t('Журнал действий')} sub={t('Каждое изменение и выгрузка: кто, когда и над чем. Журнал только дополняется.')}>
        <DownloadButton path={`/audit?format=csv${query ? '&' + query : ''}`} name="cqa-audit.csv" kind="audit-csv">
          <Download size={16} aria-hidden="true" /> {t('Скачать CSV')}
        </DownloadButton>
      </PageHead>

      <Card className="flex flex-wrap items-end gap-3 p-4" aria-label={t('Фильтры')}>
        <Field label={t('Сотрудник')}>
          <select className="fld min-w-48" data-act="filter-actor" value={f.actor} onChange={e => set('actor', e.target.value)}>
            <option value="">{t('Все')}</option>
            {(S.employees ?? []).map((e: any) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('Действие')}>
          <select className="fld min-w-56 max-w-full" data-act="filter-action" value={f.action} onChange={e => set('action', e.target.value)}>
            <option value="">{t('Все')}</option>
            {Object.entries(actionNames()).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('С даты')}>
          <input type="date" className="fld" data-act="filter-since" value={f.since} onChange={e => set('since', e.target.value)} />
        </Field>
        {query && (
          <Button variant="ghost" onClick={() => go('#/audit')}>
            {t('Сбросить фильтры')}
          </Button>
        )}
      </Card>

      <Card aria-label={t('Действия')}>
        {log.error ? (
          <div className="box risk m-4" role="alert">
            {t('Журнал не загружен: {error}', { error: log.error })}
          </div>
        ) : log.loading && !rows.length ? (
          <Skeleton className="m-4 h-40" />
        ) : rows.length ? (
          <>
            <div className="relative overflow-x-auto">
              <table className="tbl min-w-[860px]">
                <thead>
                  <tr>
                    <th>{t('Время')}</th>
                    <th>{t('Сотрудник')}</th>
                    <th>{t('Роль')}</th>
                    <th>{t('Действие')}</th>
                    <th>{t('Объект')}</th>
                    <th>{t('Подробности')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r: any) => {
                    const det = detailsText(r.details);
                    return (
                      <tr key={r.id} data-action={r.action}>
                        <td className="whitespace-nowrap">{when(r.at)}</td>
                        <td>{r.actor_id ? <a href={href('people', r.actor_id)}>{r.actor_name}</a> : <span className="text-muted">{r.actor_name || t('без входа')}</span>}</td>
                        <td>{r.role ? roleName(r.role) : '—'}</td>
                        <td>{actionName(r.action)}</td>
                        <td className="whitespace-nowrap">
                          <Target type={r.target_type} id={r.target_id} />
                        </td>
                        <td className="max-w-[320px] text-[13px] text-muted">
                          {det.length > 60 ? (
                            <Tip content={det}>
                              <span tabIndex={0} className="block truncate">
                                {det}
                              </span>
                            </Tip>
                          ) : (
                            det || '—'
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between gap-3 px-4 py-3 text-[13px] text-muted">
              <span>{t('Показано {n}, новые первыми', { n: rows.length })}</span>
              {rows.length >= limit && (
                <Button size="sm" disabled={log.loading} onClick={() => go(href('audit', null, { ...f, limit: String(limit + PAGE) }))}>
                  {log.loading ? t('Загружается…') : t('Показать ещё')}
                </Button>
              )}
            </div>
          </>
        ) : (
          <Empty action={query ? <Button onClick={() => go('#/audit')}>{t('Сбросить фильтры')}</Button> : undefined}>
            {query ? t('По этим фильтрам действий нет.') : t('Действий пока нет.')}
          </Empty>
        )}
      </Card>
    </>
  );
}
