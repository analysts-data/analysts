// Вкладка «Срезы» аналитики: GET /api/analytics/{drivers,heatmap,trend,appeals,model} с фильтрами из адреса
// (design/contract.md, «Аналитика»). Запросы — только при открытой вкладке: у сервера защиты этих путей может не быть.
// У каждой точки своё n; при low_n значение приглушено и подписано «мало данных»: выводы по нему не делаются.
// Формулы метрик (definitions) — с сервера, по-русски, в подсказках к названиям.
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { X } from 'lucide-react';
import { esc, f2, fn } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { href, parseHash } from '../../lib/router.js';
import { currentTheme, go, useRoute, useS } from '../../store';
import { Button, Card, Chip, cn, Empty, LinkButton, Skeleton, Tip } from '../../ui';
import { pct, useGet } from '../people/net';
import { NO_OPERATOR, operatorOf, productOf } from '../queue/order';
import { heat, heatStyle } from './Chart';

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

type P = Record<string, string>;
type Count = { k: number; n: number; share: number | null; low_n: boolean };
const FILTERS = ['ch', 'lang', 'product', 'operator', 'since', 'until'] as const;
const BY = ['operator', 'product', 'lang', 'ch'];

/** ?by=…&ch=…: параметры среза из адреса экрана, пустые не передаются. */
const query = (p: P, extra: P = {}) => {
  const q = new URLSearchParams(Object.entries({ ...extra, ...Object.fromEntries(FILTERS.map(k => [k, p[k]])) }).filter(([, v]) => v)).toString();
  return q ? `?${q}` : '';
};
// параметры — из хеша, а не из отрисовки: быстрый второй выбор до hashchange не теряет первый
const to = (k: string, v: string) => go(href('analytics', null, { ...parseHash(location.hash).params, [k]: v }));
const clearHref = (p: P) => href('analytics', null, Object.fromEntries(Object.entries(p).filter(([k]) => !(FILTERS as readonly string[]).includes(k))));
const few = (n: number, min: number) => t('мало данных (n={n}, нужно ≥{min})', { n, min });
const css = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${n}`).trim();
const chName = (ch: string) => (ch === 'call' ? t('Звонок') : ch === 'chat' ? t('Чат') : ch);

/** Название метрики с формулой сервера в подсказке. */
function Def({ d, k, children }: { d: any; k: string; children: React.ReactNode }) {
  const text = d?.definitions?.[k];
  if (!text) return <>{children}</>;
  return (
    <Tip content={text}>
      <span tabIndex={0} className="cursor-help underline decoration-line-strong decoration-dotted decoration-1 underline-offset-[3px]">
        {children}
      </span>
    </Tip>
  );
}

/** Значение с n: при low_n приглушено, под ним «мало данных (n=…, нужно ≥…)». */
function Val({ v, n, low, min }: { v: React.ReactNode; n: number; low: boolean; min: number }) {
  return low ? (
    <span className="low text-muted">
      {v}
      <span className="block text-xs leading-tight">{few(n, min)}</span>
    </span>
  ) : (
    <>{v}</>
  );
}

/** Счётчик {k, n, share}: доля и «k из n»; без знаменателя — «—». */
function Counter({ c, min }: { c: Count; min: number }) {
  if (!c?.n) return <>—</>;
  return (
    <Val
      v={
        <>
          {pct(c.share)} <span className="text-xs text-muted">{t('{lost} из {n}', { lost: c.k, n: c.n })}</span>
        </>
      }
      n={c.n}
      low={c.low_n}
      min={min}
    />
  );
}

function Seg({ act, label, value, options, onPick }: { act: string; label: string; value: string; options: [string, string][]; onPick: (v: string) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex shrink-0 rounded-lg border border-line-strong p-0.5">
      {options.map(([v, name]) => (
        <button
          key={v}
          type="button"
          data-act={act}
          data-by={v}
          aria-pressed={v === value}
          onClick={() => onPick(v)}
          className={cn('min-h-8 rounded-md px-3 text-[13px] font-medium', v === value ? 'bg-accent-soft text-accent-ink' : 'text-ink2 hover:bg-hover')}
        >
          {name}
        </button>
      ))}
    </div>
  );
}

/** Блок среза: заголовок с действием справа, загрузка, ошибка с повтором, пустая выборка со сбросом фильтров. */
function Block({ g, title, sub, action, children }: { g: ReturnType<typeof useGet>; title: string; sub: string; action?: React.ReactNode; children: (d: any) => React.ReactNode }) {
  const { params: p } = useRoute();
  const d: any = g.data;
  return (
    <Card aria-label={title} aria-busy={g.loading} className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-3 pt-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-[13px] text-muted">{sub}</p>
        </div>
        {action}
      </div>
      {g.error ? (
        <Empty
          action={
            <Button size="sm" onClick={g.reload}>
              {t('Повторить')}
            </Button>
          }
        >
          {t('Данные не получены: {error}', { error: g.error })}
        </Empty>
      ) : !d ? (
        <div className="px-4 pb-4">
          <Skeleton className="h-32" />
        </div>
      ) : !d.n ? (
        <Empty
          action={
            FILTERS.some(k => p[k]) ? (
              <LinkButton size="sm" href={clearHref(p)}>
                {t('Сбросить фильтры')}
              </LinkButton>
            ) : (
              <LinkButton size="sm" href="#/queue">
                {t('Перейти к диалогам')}
              </LinkButton>
            )
          }
        >
          {t('Под выбранные фильтры нет оценённых диалогов.')}
        </Empty>
      ) : (
        <div className={cn('transition-opacity', g.loading && 'opacity-60')}>{children(d)}</div>
      )}
    </Card>
  );
}

function Filters({ p }: { p: P }) {
  const S = useS();
  const all = t('Все');
  const ops = S.dialogs.some((d: any) => d.operator) ? [...new Set<string>(S.dialogs.map(operatorOf))].sort() : [];
  const products = [...new Map<string, string>(S.dialogs.map(productOf).filter(Boolean).map((x: any) => [x.id, x.name || x.id]))];
  const sel = (k: string, label: string, vals: [string, string][]) => (
    <label className="flex items-center gap-2 text-[13px] text-muted">
      {label}
      <select className="fld" data-act="filter" data-key={k} value={p[k] || ''} onChange={e => to(k, e.target.value)}>
        {[['', all] as [string, string], ...vals].map(([v, name]) => (
          <option key={v} value={v}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
  const date = (k: string, label: string) => (
    <label className="flex items-center gap-2 text-[13px] text-muted">
      {label}
      <input type="date" className="fld" data-act="filter" data-key={k} value={p[k] || ''} onChange={e => to(k, e.target.value)} />
    </label>
  );
  return (
    <div role="group" aria-label={t('Фильтры среза')} className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {sel('ch', t('Канал'), [
        ['chat', t('Чат')],
        ['call', t('Звонок')],
      ])}
      {sel('lang', t('Язык'), [
        ['RU', 'RU'],
        ['KZ', 'KZ'],
        ['EN', 'EN'],
      ])}
      {products.length > 0 && sel('product', t('Продукт'), products)}
      {ops.length > 0 && sel('operator', t('Оператор'), ops.map((o): [string, string] => [o, o === NO_OPERATOR ? t('Не указан') : o]))}
      {date('since', t('С даты'))}
      {date('until', t('По дату'))}
      {FILTERS.some(k => p[k]) && (
        <LinkButton size="sm" variant="ghost" href={clearHref(p)} data-act="clear">
          <X size={16} aria-hidden="true" /> {t('Сбросить фильтры')}
        </LinkButton>
      )}
    </div>
  );
}

function Drivers({ p }: { p: P }) {
  const g = useGet(`/analytics/drivers${query(p)}`);
  return (
    <Block g={g} title={t('Что сильнее всего снижает итог')} sub={t('На сколько вырастет средний итог, если поднять критерий до максимума везде, где он применим. Это связь, а не причина.')}>
      {d => {
        const top = d.drivers.find((x: any) => !x.low_n && x.uplift > 0);
        return (
          <>
            <p className="px-4 pb-3 text-[15px]" data-act="headline">
              {top
                ? t('Исправлять первым: «{name}», +{uplift} к среднему итогу {base}.', { name: top.name, uplift: f2(top.uplift), base: f2(d.base) })
                : t('Вывода нет: по каждому критерию мало данных или итог уже максимальный.')}{' '}
              <span className="text-[13px] text-muted">{t('Выборка: {n} оценённых диалогов.', { n: d.n })}</span>
            </p>
            <div className="relative overflow-x-auto">
              <table className="tbl min-w-[880px]">
                <thead>
                  <tr>
                    <th>{t('Критерий')}</th>
                    <th>{t('Если поднять до максимума')}</th>
                    <th className="num">
                      <Def d={d} k="uplift">
                        {t('Прирост')}
                      </Def>
                    </th>
                    <th className="num">
                      <Def d={d} k="gap">
                        {t('Разрыв')}
                      </Def>
                    </th>
                    <th className="num">
                      <Def d={d} k="n">
                        n
                      </Def>
                    </th>
                    <th>
                      <Def d={d} k="at_max">
                        {t('Ниже максимума')}
                      </Def>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d.drivers.map((x: any) => {
                    const minN = Math.min(x.at_max.n, x.below_max.n);
                    return (
                      <tr key={x.id} data-cid={x.id} className={x.low_n ? 'low' : undefined}>
                        <td>
                          <span className="text-muted">{x.id}</span> {x.name}
                          {x.low_n && (
                            <div className="mt-1">
                              <Chip tone="na">{few(minN, d.min_n)}</Chip>
                            </div>
                          )}
                        </td>
                        <td className={cn('text-[13px]', x.low_n && 'text-muted')}>
                          {/* сервер присылает фразу по-русски; числа те же, фраза собирается на языке интерфейса */}
                          {x.what_if == null || x.uplift == null || x.avg_total_if_max == null
                            ? (x.what_if ?? '—')
                            : t('Если поднять «{name}» до максимума во всех {n} диалогах, где он применим, средний итог вырастет на {uplift} балла: с {base} до {after}.', {
                                name: x.name,
                                n: x.n,
                                uplift: f2(x.uplift),
                                base: f2(d.base),
                                after: f2(x.avg_total_if_max),
                              })}
                        </td>
                        <td className={cn('num font-semibold', x.low_n && 'text-muted')}>{x.uplift == null ? '—' : `+${f2(x.uplift)}`}</td>
                        <td className={cn('num', x.low_n && 'text-muted')}>{f2(x.gap)}</td>
                        <td className="num">{x.n}</td>
                        <td className="whitespace-nowrap">
                          {x.below_max.n ? (
                            <a href={href('queue', null, { lost: x.id, lang: p.lang, ch: p.ch, op: p.operator, prod: p.product })}>{t('Открыть {n}', { n: x.below_max.n })}</a>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        );
      }}
    </Block>
  );
}

function Heatmap({ p }: { p: P }) {
  const by = BY.includes(p.by) ? p.by : 'operator';
  const g = useGet(`/analytics/heatmap${query(p, { by })}`);
  const dark = currentTheme() === 'dark';
  const names: Record<string, string> = { operator: t('Оператор'), product: t('Продукт'), lang: t('Язык'), ch: t('Канал') };
  const cell = (c: any, min: number) =>
    c?.share == null ? (
      <div className="heat grid min-h-11 place-items-center rounded text-[13px]" style={heatStyle(0, dark)}>
        —
      </div>
    ) : (
      <div
        className={cn('heat grid min-h-11 place-content-center rounded px-1 text-center', c.low_n && 'low')}
        style={c.low_n ? { background: 'var(--sunken)', color: 'var(--muted)' } : heatStyle(heat(1 - c.share, 1), dark)}
      >
        <b className={cn('text-[13px]', c.low_n && 'font-medium')}>{pct(c.share)}</b>
        <span className="text-[11px] leading-tight">{c.low_n ? t('мало данных, n={n}', { n: c.n }) : `n=${c.n}`}</span>
      </div>
    );
  return (
    <Block
      g={g}
      title={t('Тепловая карта')}
      sub={t('Средняя доля балла по критерию в каждой группе. Чем насыщеннее цвет, тем больше теряют.')}
      action={<Seg act="by" label={t('Строки тепловой карты')} value={by} options={BY.map(k => [k, names[k]])} onPick={v => to('by', v)} />}
    >
      {d => (
        <>
          <div className="relative overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>
                    <Def d={d} k="rows">
                      {names[by]}
                    </Def>
                  </th>
                  <th className="num">n</th>
                  <th className="num">
                    <Def d={d} k="avg_total">
                      {t('Средний итог')}
                    </Def>
                  </th>
                  {d.columns.map((c: any) => (
                    <th key={c.id} className="num">
                      <Tip content={c.name}>
                        <span tabIndex={0}>{c.id}</span>
                      </Tip>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r: any) => (
                  <tr key={r.key ?? ''} data-key={r.key ?? ''}>
                    <td className="whitespace-nowrap font-semibold">{r.key == null ? t('Не указан') : by === 'ch' ? chName(r.key) : r.label}</td>
                    <td className="num">{r.n}</td>
                    <td className="num">
                      <Val v={f2(r.avg_total)} n={r.n} low={r.low_n} min={d.min_n} />
                    </td>
                    {d.columns.map((c: any) => (
                      <td key={c.id} className="min-w-[84px] !p-1">
                        {cell(r.cells[c.id], d.min_n)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="font-semibold">{t('Вся выборка')}</td>
                  <td className="num">{d.n}</td>
                  <td />
                  {d.columns.map((c: any) => (
                    <td key={c.id} className="!p-1">
                      {cell({ ...c, low_n: c.n < d.min_n }, d.min_n)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="px-4 py-3 text-xs text-muted">{t('В ячейке средняя доля балла и n. Серая ячейка: мало данных (n меньше {min}), сравнивать её нельзя.', { min: d.min_n })}</p>
        </>
      )}
    </Block>
  );
}

function Trend({ p }: { p: P }) {
  const per = p.per === 'week' ? 'week' : 'day';
  const g = useGet(`/analytics/trend${query(p, { by: per })}`);
  currentTheme(); // токены читаются при каждой отрисовке: смена темы зовёт rerender
  return (
    <Block
      g={g}
      title={t('Тренд')}
      sub={t('Средний итог по периодам. Полая точка: мало данных, по ней выводов не делают.')}
      action={
        <Seg
          act="per"
          label={t('Период тренда')}
          value={per}
          options={[
            ['day', t('По дням')],
            ['week', t('По неделям')],
          ]}
          onPick={v => to('per', v === 'day' ? '' : v)}
        />
      }
    >
      {d => {
        const pts: any[] = d.points;
        const muted = css('muted'),
          accent = css('accent');
        const day = (x: any) => (per === 'week' ? x.period.slice(5) : `${x.period.slice(8)}.${x.period.slice(5, 7)}`);
        const cnt = (c: Count) => t('{lost} из {n}', { lost: c.k, n: c.n });
        const tip = (x: any) =>
          [
            `<b>${esc(x.period)}</b>`,
            `${esc(t('Средний итог'))}: <b>${esc(f2(x.avg_total))}</b> (n=${x.n})`,
            `${esc(t('Грубые ошибки'))}: ${esc(cnt(x.gross))}`,
            `${esc(t('Без следующего шага'))}: ${esc(cnt(x.no_next_step))}`,
            `${esc(t('Нужна проверка'))}: ${esc(cnt(x.needs_review))}`,
            x.low_n ? esc(few(x.n, d.min_n)) : '',
          ]
            .filter(Boolean)
            .join('<br>');
        // Без анимации, градиентов и легенды; полая точка — low_n.
        const option = {
          animation: false,
          textStyle: { fontFamily: css('font'), fontSize: 12 },
          grid: { left: 8, right: 16, top: 12, bottom: 4, containLabel: true },
          tooltip: {
            trigger: 'axis',
            confine: true,
            backgroundColor: css('surface'),
            borderColor: css('line'),
            textStyle: { color: css('ink'), fontSize: 12 },
            extraCssText: 'box-shadow: var(--shadow)',
            axisPointer: { type: 'line', lineStyle: { color: css('line-strong') } },
            formatter: (ps: { dataIndex: number }[]) => tip(pts[ps[0].dataIndex]),
          },
          xAxis: {
            type: 'category',
            data: pts.map(x => `${day(x)}\nn=${x.n}`),
            axisTick: { show: false },
            axisLine: { lineStyle: { color: css('line-strong'), width: 1 } },
            axisLabel: { color: muted, fontSize: 12, lineHeight: 15 },
          },
          yAxis: {
            type: 'value',
            min: (v: { min: number }) => Math.max(0, Math.floor(v.min / 10) * 10 - 10),
            max: 100,
            splitNumber: 4,
            axisLabel: { color: muted },
            splitLine: { lineStyle: { color: css('line2') } },
          },
          series: [
            {
              type: 'line',
              showAllSymbol: true,
              symbol: 'circle',
              symbolSize: 8,
              lineStyle: { color: accent, width: 2 },
              data: pts.map(x => ({
                value: x.avg_total,
                itemStyle: x.low_n ? { color: css('surface'), borderColor: muted, borderWidth: 2 } : { color: accent, borderColor: accent },
              })),
            },
          ],
        };
        return (
          <div className="px-4 pb-4">
            <div aria-hidden="true">
              <ReactEChartsCore echarts={echarts} option={option} notMerge style={{ height: 240, width: '100%' }} />
            </div>
            <ul className="sr" aria-label={t('Точки тренда')}>
              {pts.map(x => (
                <li key={x.period} data-low={x.low_n || undefined}>
                  {x.period}: {f2(x.avg_total)}, n={x.n}
                  {x.low_n ? `, ${few(x.n, d.min_n)}` : ''}
                </li>
              ))}
            </ul>
          </div>
        );
      }}
    </Block>
  );
}

function Appeals({ p }: { p: P }) {
  const g = useGet(`/analytics/appeals${query(p)}`);
  return (
    <Block g={g} title={t('Апелляции')} sub={t('Как часто решение по апелляции или проверке меняет ответ и сколько ждут решения.')}>
      {d => {
        const s = d.summary;
        if (!s.filed && !s.reviews) return <p className="px-4 pb-4 text-[13px] text-muted">{t('По выбранным диалогам апелляций и проверок нет.')}</p>;
        const stat = (label: React.ReactNode, value: React.ReactNode, note: React.ReactNode) => (
          <div className="bg-surface px-4 py-3">
            <div className="text-[13px] text-muted">{label}</div>
            <div className="text-xl font-semibold">{value}</div>
            <div className="text-xs text-muted">{note}</div>
          </div>
        );
        const hours = (h: number | null) => (h == null ? '—' : t('{h} ч', { h: fn(h) }));
        return (
          <>
            <div className="grid grid-cols-2 gap-px border-y border-line2 bg-line2 sm:grid-cols-4">
              {stat(<Def d={d} k="decisions">{t('Подано апелляций')}</Def>, s.filed, t('проверок специалиста: {n}', { n: s.reviews }))}
              {stat(t('Ждут решения'), s.pending, t('закрыто без решения: {n}', { n: s.closed }))}
              {stat(
                <Def d={d} k="changed_share">
                  {t('Решение изменило ответ')}
                </Def>,
                <Val v={pct(s.changed_share)} n={s.decided} low={s.low_n} min={d.min_n} />,
                t('{lost} из {n}', { lost: s.changed, n: s.decided }),
              )}
              {stat(
                <Def d={d} k="median_hours">
                  {t('Медиана до решения')}
                </Def>,
                hours(s.median_hours),
                `n=${s.timed}`,
              )}
            </div>
            <div className="grid gap-4 p-4 lg:grid-cols-2">
              <div className="min-w-0">
                <h3 className="mb-1 text-[13px] font-semibold text-muted">{t('По критериям')}</h3>
                <div className="relative overflow-x-auto">
                  <table className="tbl" aria-label={t('Апелляции по критериям')}>
                    <thead>
                      <tr>
                        <th>{t('Критерий')}</th>
                        <th className="num">{t('Решено')}</th>
                        <th className="num">{t('Изменено')}</th>
                        <th className="num">{t('Доля изменений')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.criteria.map((x: any) => (
                        <tr key={x.id}>
                          <td>
                            <span className="text-muted">{x.id}</span> {x.name}
                          </td>
                          <td className="num">{x.decided}</td>
                          <td className="num">{x.changed}</td>
                          <td className="num">
                            <Val v={pct(x.changed_share)} n={x.decided} low={x.low_n} min={d.min_n} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="min-w-0">
                <h3 className="mb-1 text-[13px] font-semibold text-muted">
                  <Def d={d} k="reviewers">
                    {t('По проверяющим')}
                  </Def>
                </h3>
                {d.reviewers.length ? (
                  <div className="relative overflow-x-auto">
                    <table className="tbl" aria-label={t('Апелляции по проверяющим')}>
                      <thead>
                        <tr>
                          <th>{t('Проверяющий')}</th>
                          <th className="num">{t('Решено')}</th>
                          <th className="num">{t('Доля изменений')}</th>
                          <th className="num">{t('Медиана до решения')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.reviewers.map((x: any) => (
                          <tr key={x.reviewer}>
                            <td>{x.reviewer === NO_OPERATOR ? t('Не указан') : x.reviewer}</td>
                            <td className="num">{x.decided}</td>
                            <td className="num">
                              <Val v={pct(x.changed_share)} n={x.decided} low={x.low_n} min={d.min_n} />
                            </td>
                            <td className="num">
                              {hours(x.median_hours)} <span className="text-xs text-muted">n={x.timed}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-[13px] text-muted">{t('Решений пока нет.')}</p>
                )}
              </div>
            </div>
          </>
        );
      }}
    </Block>
  );
}

function Model({ p }: { p: P }) {
  const g = useGet(`/analytics/model${query(p)}`);
  return (
    <Block g={g} title={t('Качество модели')} sub={t('По ответам модели без решений людей: где второе мнение расходится, основание не подтверждено или ответ поставлен вручную.')}>
      {d => (
        <>
          <div className="relative overflow-x-auto">
            <table className="tbl min-w-[760px]" aria-label={t('Сигналы модели по критериям')}>
              <thead>
                <tr>
                  <th>{t('Критерий')}</th>
                  <th className="num">
                    <Def d={d} k="results">
                      {t('Ответов')}
                    </Def>
                  </th>
                  <th className="num">
                    <Def d={d} k="second_opinion">
                      {t('Второе мнение совпало')}
                    </Def>
                  </th>
                  <th className="num">
                    <Def d={d} k="ev_fail">
                      {t('Основание не подтверждено')}
                    </Def>
                  </th>
                  <th className="num">
                    <Def d={d} k="jev_unsure">
                      {t('Jev не уверен')}
                    </Def>
                  </th>
                  <th className="num">
                    <Def d={d} k="manual">
                      {t('Вручную')}
                    </Def>
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.criteria.map((x: any) => (
                  <tr key={x.id}>
                    <td>
                      <span className="text-muted">{x.id}</span> {x.name}
                    </td>
                    <td className="num">{x.results}</td>
                    {(['second_opinion', 'ev_fail', 'jev_unsure', 'manual'] as const).map(k => (
                      <td key={k} className="num" data-metric={k}>
                        <Counter c={x[k]} min={d.min_n} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="p-4">
            <h3 className="mb-1 text-[13px] font-semibold text-muted">
              <Def d={d} k="cost">
                {t('Стоимость оценки по дням')}
              </Def>
            </h3>
            {d.cost.length ? (
              <div className="relative overflow-x-auto">
                <table className="tbl" aria-label={t('Стоимость оценки по дням')}>
                  <thead>
                    <tr>
                      <th>{t('Период')}</th>
                      <th className="num">n</th>
                      <th className="num">{t('$ на диалог')}</th>
                      <th className="num">{t('Секунд на диалог')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.cost.map((x: any) => (
                      <tr key={x.period}>
                        <td>
                          <Val v={x.period} n={x.n} low={x.low_n} min={d.min_n} />
                        </td>
                        <td className="num">{x.n}</td>
                        <td className="num">${x.avg_usd.toFixed(4)}</td>
                        <td className="num">{fn(x.avg_s)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[13px] text-muted">{t('Данных о стоимости нет.')}</p>
            )}
          </div>
        </>
      )}
    </Block>
  );
}

export function Slices() {
  const { params: p } = useRoute();
  return (
    <>
      <Filters p={p} />
      <Drivers p={p} />
      <Heatmap p={p} />
      <Trend p={p} />
      <Appeals p={p} />
      <Model p={p} />
    </>
  );
}
