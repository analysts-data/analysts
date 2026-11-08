// Столбчатый график ECharts (echarts/core: только BarChart, сетка и подсказка) и те же числа текстом под ним:
// холст скрыт от чтения с экрана, числа остаются читаемыми и без графика. Цвета — токены темы.
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { esc } from '../../lib/format.js';
import { currentTheme, go } from '../../store';
import { Term, type TermKey } from '../../terms';
import { Card } from '../../ui';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

/** Столбец: name — подпись, value — длина, label — число для показа, href — список диалогов за числом. */
export type Bar = { name: string; value: number; label: string; href?: string };

const css = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${n}`).trim();

export function Chart({
  title,
  term,
  caption,
  rows,
  color = 'accent',
  vertical,
  action,
}: {
  title: string;
  term?: TermKey;
  caption: string;
  rows: Bar[];
  color?: string;
  vertical?: boolean;
  action?: React.ReactNode;
}) {
  currentTheme(); // токены читаются при каждой отрисовке: смена темы зовёт rerender
  const muted = css('muted');
  const cat = {
    type: 'category',
    data: rows.map(r => r.name),
    inverse: !vertical,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: css('line-strong'), width: 1 } },
    axisLabel: { color: muted, fontSize: 12, width: vertical ? undefined : Math.min(190, innerWidth * 0.35), overflow: 'truncate', interval: 0 },
  };
  const val = { type: 'value', show: false, max: (v: { max: number }) => Math.max(1, v.max) };
  // Без анимации загрузки, градиентов и легенд: подписи прямо на столбцах.
  const option = {
    animation: false,
    textStyle: { fontFamily: css('font'), fontSize: 12 },
    grid: { left: 12, right: vertical ? 4 : 44, top: vertical ? 20 : 4, bottom: 4, containLabel: true },
    // подпись из данных сервера уходит в HTML подсказки только через esc
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: css('surface'),
      borderColor: css('line'),
      textStyle: { color: css('ink'), fontSize: 12 },
      extraCssText: 'box-shadow: var(--shadow)',
      formatter: (p: { dataIndex: number }) => `${esc(rows[p.dataIndex].name)}: <b>${esc(rows[p.dataIndex].label)}</b>`,
    },
    xAxis: vertical ? cat : val,
    yAxis: vertical ? val : cat,
    series: [
      {
        type: 'bar',
        data: rows.map(r => r.value),
        barMaxWidth: 26,
        cursor: rows.some(r => r.href) ? 'pointer' : 'default',
        itemStyle: { color: css(color), borderRadius: vertical ? [3, 3, 0, 0] : [0, 3, 3, 0] },
        label: { show: true, position: vertical ? 'top' : 'right', color: css('ink'), fontSize: 12, fontWeight: 600, formatter: (p: { dataIndex: number }) => rows[p.dataIndex].label },
      },
    ],
  };
  const height = vertical ? 200 : rows.length * 30 + 12;
  return (
    <Card className="flex min-w-0 flex-col gap-3 p-4" aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{term ? <Term k={term}>{title}</Term> : title}</h2>
          <p className="text-[13px] text-muted">{caption}</p>
        </div>
        {action}
      </div>
      {rows.length ? (
        <div aria-hidden="true">
          <ReactEChartsCore
            echarts={echarts}
            option={option}
            notMerge
            style={{ height, width: '100%' }}
            onEvents={{ click: (p: { dataIndex: number }) => rows[p.dataIndex]?.href && go(rows[p.dataIndex].href) }}
          />
        </div>
      ) : null}
      <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-muted">
        {rows.map(r => (
          <li key={r.name}>
            {r.href ? (
              <a href={r.href} className="text-muted no-underline hover:underline">
                {r.name}: <b className="text-ink">{r.label}</b>
              </a>
            ) : (
              <>
                {r.name}: <b className="text-ink">{r.label}</b>
              </>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
