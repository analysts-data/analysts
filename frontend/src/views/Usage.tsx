// «Использование»: метрики взаимодействия из POST /api/telemetry, сводка GET /api/usage?since=&role=.
// Текста диалогов и поисковых строк в метриках нет: только экраны, действия, воронки, ошибки и выгрузки.
import { Download } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { mmss } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { go, useRoute } from '../store';
import { Card, Empty, Field, PageHead, Skeleton } from '../ui';
import { actionName, DownloadButton, pct, roleNames, useGet } from './people/net';

const Chart = lazy(() => import('./analytics/Chart').then(m => ({ default: m.Chart })));

const weekAgo = () => new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10);
const screens = (): Record<string, string> => ({
  queue: t('Диалоги'),
  d: t('Карточка разговора'),
  card: t('Карточка разговора'),
  appeals: t('Апелляции'),
  analytics: t('Аналитика'),
  coaching: t('Обучение'),
  checklist: t('Чек-лист'),
  alerts: t('Алерты'),
  people: t('Сотрудники'),
  audit: t('Журнал действий'),
  reports: t('Отчёты'),
  usage: t('Использование'),
});
const screen = (p: string) => screens()[String(p).replace(/^#?\/?/, '').split('/')[0]] ?? p;

function Table({ title, caption, head, rows }: { title: string; caption?: string; head: string[]; rows: React.ReactNode[][] }) {
  return (
    <Card aria-label={title} className="min-w-0">
      <div className="px-4 pb-1.5 pt-4">
        <h2 className="text-base font-semibold">{title}</h2>
        {caption && <p className="text-[13px] text-muted">{caption}</p>}
      </div>
      {rows.length ? (
        <div className="relative overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                {head.map((h, i) => (
                  <th key={h} className={i ? 'num' : undefined}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, k) => (
                <tr key={k}>
                  {r.map((c, i) => (
                    <td key={i} className={i ? 'num' : undefined}>
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 pb-4 text-[13px] text-muted">{t('За период событий нет.')}</p>
      )}
    </Card>
  );
}

export function Usage({ id }: { id: string | null }) {
  const { params } = useRoute();
  const since = params.since || weekAgo();
  const role = params.role ?? '';
  const query = new URLSearchParams(Object.entries({ since, role }).filter(([, v]) => v)).toString();
  const u = useGet(`/usage?${query}`);
  const d: any = u.data;
  const set = (k: string, v: string) => go(href('usage', null, { since, role, [k]: v }));
  const days: any[] = d?.active_users ?? [];

  return (
    <>
      <PageHead title={t('Использование')} sub={t('Как люди работают с системой: экраны, действия, воронки и ошибки. Текст диалогов не собирается.')}>
        <DownloadButton path={`/usage?format=csv&${query}`} name="usage.csv" kind="usage-csv">
          <Download size={16} aria-hidden="true" /> {t('Скачать CSV')}
        </DownloadButton>
      </PageHead>
      <Card className="flex flex-wrap items-end gap-3 p-4" aria-label={t('Фильтры')}>
        <Field label={t('С даты')}>
          <input type="date" className="fld" data-act="filter-since" value={since} onChange={e => set('since', e.target.value)} />
        </Field>
        <Field label={t('Роль')}>
          <select className="fld min-w-48" data-act="filter-role" value={role} onChange={e => set('role', e.target.value)}>
            <option value="">{t('Все')}</option>
            {Object.entries(roleNames()).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
      </Card>

      {u.error ? (
        <div className="box risk" role="alert">
          {t('Метрики не загружены: {error}', { error: u.error })}
        </div>
      ) : !d ? (
        <Skeleton className="h-60" />
      ) : !d.events ? (
        <Card>
          <Empty>{t('За период событий нет. Метрики появляются, когда сотрудники открывают экраны и нажимают кнопки.')}</Empty>
        </Card>
      ) : (
        <>
          <Card aria-label={t('Сводка')}>
            <div className="grid grid-cols-1 divide-y divide-line2 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              {[
                [d.events, t('событий за период')],
                [days.length ? Math.max(...days.map(x => x.users)) : 0, t('активных сотрудников в лучший день')],
                [(d.screens ?? []).reduce((s: number, x: any) => s + (x.views ?? 0), 0), t('открытий экранов')],
              ].map(([v, label]) => (
                <div key={label as string} className="px-4 py-3">
                  <strong className="block text-[28px] font-bold leading-tight">{v}</strong>
                  <span className="text-[13px] text-muted">{label}</span>
                </div>
              ))}
            </div>
          </Card>
          {days.length > 0 && (
            <Suspense fallback={<Skeleton className="h-56" />}>
              <Chart
                title={t('Активные сотрудники по дням')}
                caption={t('Сколько разных сотрудников работали в системе за день, по времени Астаны.')}
                rows={days.map(x => ({ name: x.day.slice(5).split('-').reverse().join('.'), value: x.users, label: String(x.users) }))}
                vertical
              />
            </Suspense>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <Table
              title={t('Экраны')}
              caption={t('Открытия и медианное время на экране.')}
              head={[t('Экран'), t('Открытий'), t('Событий'), t('Медиана времени')]}
              rows={(d.screens ?? []).map((x: any) => [screen(x.page), x.views, x.events, x.median_ms == null ? '—' : mmss(x.median_ms / 1000)])}
            />
            <Table title={t('Действия')} caption={t('Самые частые кнопки, топ-10.')} head={[t('Действие'), t('Нажатий')]} rows={(d.actions ?? []).map((x: any) => [actionName(x.act), x.n])} />
          </div>
          <Table
            title={t('Воронки')}
            caption={t('Доля сотрудников, дошедших до действия, и медианное время от открытия до действия.')}
            head={[t('Путь'), t('Начали'), t('Дошли'), t('Доля'), t('Медиана')]}
            rows={(d.funnels ?? []).map((x: any) => [x.name, x.started, x.converted, pct(x.rate), x.median_s == null ? '—' : mmss(x.median_s)])}
          />
          <div className="grid gap-4 lg:grid-cols-2">
            <Table title={t('Ошибки на экранах')} head={[t('Экран и код'), t('Раз')]} rows={(d.errors ?? []).map((x: any) => [`${screen(x.page)}: ${x.code}`, x.n])} />
            <Table
              title={t('Выгрузки и отчёты')}
              head={[t('Что'), t('Раз')]}
              rows={[...(d.exports ?? []).map((x: any) => [t('Выгрузка {kind}', { kind: x.kind }), x.n]), ...(d.reports ?? []).map((x: any) => [t('Отчёт {kind}', { kind: x.kind }), x.n])]}
            />
          </div>
        </>
      )}
    </>
  );
}
