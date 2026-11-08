// «Отчёты»: каталог GET /api/reports. В href_template подставляются {format}, {id} — элемент списка items (прогоны,
// замеры), {from} — версия чек-листа. HTML открывается в новой вкладке, остальные форматы скачиваются.
// Сервер без каталога: показываем отчёты, которые есть всегда (отчёт для руководства, оценки, чек-лист).
import { Download, ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { t } from '../lib/i18n.js';
import { useS } from '../store';
import { Card, Field, LinkButton, PageHead, Skeleton } from '../ui';
import { apiUrl, DownloadButton, listOf, useGet, when } from './people/net';

const fallback = () => [
  { id: 'executive', title: t('Отчёт для руководства'), description: t('Сводка качества, риски, причины и выводы на одной странице A4.'), formats: ['html', 'md', 'json'], href_template: '/api/report?format={format}' },
  { id: 'scores', title: t('Оценки по диалогам'), description: t('Строка на диалог: итог, грубые ошибки и ответ по каждому критерию. Для Excel.'), formats: ['csv'], href_template: '/api/scores/export?format={format}&shape=wide' },
  { id: 'scores-long', title: t('Оценки по критериям'), description: t('Строка на пару «диалог, критерий»: ответ, обоснование, причина, модель и решение проверяющего.'), formats: ['csv'], href_template: '/api/scores/export?format={format}&shape=long' },
];
const formats = (): Record<string, string> => ({ html: t('Открыть'), md: 'Markdown', json: 'JSON', csv: 'CSV' });
const fill = (tpl: string, v: Record<string, string>) => tpl.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(v[k] ?? ''));
const itemLabel = (x: any) => [t('№ {id}', { id: x.id }), x.created && when(x.created), x.model, x.status === 'running' ? t('идёт') : null].filter(Boolean).join(', ');

function Report({ r }: { r: any }) {
  const S = useS();
  const tpl: string = r.href_template;
  const needId = tpl.includes('{id}');
  const needFrom = tpl.includes('{from}');
  const items = useGet(needId && r.items ? r.items.replace(/^\/api(?=\/)/, '') : null);
  const list = listOf(items.data);
  const [id, setId] = useState('');
  const [from, setFrom] = useState('');
  const pickedId = id || String(list[0]?.id ?? '');
  const versions: any[] = S.versions ?? [];
  const pickedFrom = from || String(versions.at(-2)?.v ?? versions[0]?.v ?? '');
  const ready = (!needId || pickedId) && (!needFrom || pickedFrom);
  const url = (format: string) => fill(tpl, { format, id: pickedId, from: pickedFrom });

  return (
    <li className="flex flex-col gap-3 px-4 py-4 md:flex-row md:items-center md:justify-between" data-report={r.id}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold">{r.title}</h2>
        {r.description && <p className="text-[13px] text-muted">{r.description}</p>}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {needId &&
          (items.loading ? (
            <Skeleton className="h-8 w-48" />
          ) : list.length ? (
            <Field label={r.id === 'run' ? t('Прогон') : r.id === 'quality' ? t('Замер') : t('Какой отчёт')}>
              <select className="fld min-h-8 text-[13px]" value={pickedId} onChange={e => setId(e.target.value)}>
                {list.map((x: any) => (
                  <option key={x.id} value={x.id}>
                    {itemLabel(x)}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <span className="text-[13px] text-muted">{items.error ? t('Список недоступен: {error}', { error: items.error }) : t('Пока нет ни одного')}</span>
          ))}
        {needFrom && (
          <Field label={t('С версии')}>
            <select className="fld min-h-8 text-[13px]" value={pickedFrom} onChange={e => setFrom(e.target.value)}>
              {versions.map((v: any) => (
                <option key={v.v} value={v.v}>
                  {t('v{v}', { v: v.v })}
                </option>
              ))}
            </select>
          </Field>
        )}
        {ready &&
          (r.formats ?? []).map((f: string) =>
            f === 'html' ? (
              <LinkButton key={f} size="sm" href={apiUrl(url(f))} target="_blank" rel="noopener">
                <ExternalLink size={16} aria-hidden="true" /> {formats()[f]}
              </LinkButton>
            ) : (
              <DownloadButton key={f} path={url(f)} name={`${r.id}.${f}`} kind={`${r.id}-${f}`}>
                <Download size={16} aria-hidden="true" /> {formats()[f] ?? f}
              </DownloadButton>
            ),
          )}
      </div>
    </li>
  );
}

export function Reports({ id }: { id: string | null }) {
  const cat = useGet('/reports');
  const reports = cat.error ? fallback() : listOf(cat.data);
  return (
    <>
      <PageHead title={t('Отчёты')} sub={t('Все отчёты в одном месте: HTML для печати, Markdown для вики и почты, JSON и CSV для анализа.')} />
      {cat.error && <p className="text-[13px] text-muted">{t('Каталог отчётов на сервере недоступен, показаны основные отчёты.')}</p>}
      <Card aria-label={t('Каталог отчётов')}>
        {cat.loading ? (
          <Skeleton className="m-4 h-40" />
        ) : (
          <ul className="m-0 list-none divide-y divide-line2 p-0">
            {reports.map((r: any) => (
              <Report key={r.id} r={r} />
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
