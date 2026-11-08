// Экран «Аналитика»: каждое число открывает список диалогов, из него карточку и реплику.
// Числа — из lib/analytics.js и lib/scoring.js; здесь только раскладка, графики и действия.
import { Download, Printer } from 'lucide-react';
import { useState } from 'react';
import { criteriaStats, flagStats, nextStepStats, qualityStats, reasonsCsv, reasonsStats, resultsCsv } from '../lib/analytics.js';
import { resolveBase } from '../lib/api.js';
import { f2, fn, titleOf } from '../lib/format.js';
import { twoModels } from '../lib/queue.js';
import { href } from '../lib/router.js';
import { calc, r2 } from '../lib/scoring.js';
import { t } from '../lib/i18n.js';
import { api, toast } from '../lib/state.js';
import { currentTheme, go, rerender, useRoute, useS } from '../store';
import { Term, TERMS } from '../terms';
import { Button, Card, Chip, cn, Empty, LinkButton, PageHead, Tip } from '../ui';
import { Recommendations } from './Recommendations';
import { Chart, type Bar } from './analytics/Chart';
import { Products } from './analytics/Products';
import { Runs } from './analytics/Runs';
import { DownloadButton } from './people/net';

// Вкладки: «Обзор» считается из /api/state; остальные зовут новые пути сервера только при открытии вкладки.
const TABS = ['overview', 'products', 'runs'] as const;
const tabName = (k: string) => ({ overview: t('Обзор'), products: t('По продуктам'), runs: t('Прогоны') })[k];

const LANGS = ['RU', 'KZ', 'EN'];
// значения — данные сервера (PUT /api/owners), переводится только подпись
const OWNERS = ['Не назначено', 'Инструкция', 'Сервис', 'Продукт'];
const ownerName = (o: string) => ({ 'Не назначено': t('Не назначено'), Инструкция: t('Инструкция'), Сервис: t('Сервис'), Продукт: t('Продукт') })[o] ?? o;
// диапазоны итога для распределения: [подпись, нижняя граница]
const BANDS: [string, number][] = [
  ['до 50', 0],
  ['50–69', 50],
  ['70–79', 70],
  ['80–89', 80],
  ['90–100', 90],
];
const pct = (x: number | null) => (x == null ? '—' : `${Math.round(100 * x)}%`);
const lost = (cid: string, lang?: string) => href('queue', null, { lost: cid, lang });
// 0..4: насколько часто теряют баллы (классы hm* — метки старой вёрстки)
const heat = (k: number, n: number) => (!n ? 0 : k / n >= 0.6 ? 4 : k / n >= 0.4 ? 3 : k / n >= 0.2 ? 2 : k ? 1 : 0);
const HEAT_BG = [
  'var(--sunken)',
  'color-mix(in srgb, var(--ev) 14%, var(--surface))',
  'color-mix(in srgb, var(--ev) 32%, var(--surface))',
  'color-mix(in srgb, var(--ev) 58%, var(--surface))',
  'var(--ev)',
];
// в тёмной теме насыщенная ячейка светлая: текст на ней тёмный, иначе контраст ниже 4,5:1
const heatStyle = (h: number, dark: boolean) => ({
  background: HEAT_BG[h],
  color: h === 4 ? 'var(--surface)' : h === 3 && dark ? 'var(--bg)' : h ? 'var(--ink)' : 'var(--muted)',
});

function download(name: string, text: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

// Отчёт для руководства (GET {api}/report): адрес API тот же, что у main.tsx; фильтров на экране нет, параметры не нужны.
const reportUrl = (fmt = '') => `${resolveBase(location.search, document.querySelector<HTMLElement>('cqa-app')?.dataset.api)}/report${fmt}`;

const TILE = 'flex min-w-0 flex-col gap-1.5 bg-surface px-4 py-3.5 text-ink no-underline transition-colors hover:bg-hover';

/** Плитка сводки: показатель, число в <strong>, пояснение и рубрика мелко; со ссылкой — <a>, иначе <div>. */
function Tile({ label, value, hint, rubric, children, ...a }: { label: string; value: React.ReactNode; hint: string; rubric?: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const body = (
    <>
      <span className="text-[13px] font-semibold text-ink2">{label}</span>
      <strong className="text-[28px] font-bold leading-tight">{value}</strong>
      <span className="text-[13px] text-ink2">{children}</span>
      {rubric && <span className="text-xs text-muted">{rubric}</span>}
    </>
  );
  return (
    <Tip content={hint}>
      {a.href ? (
        <a className={cn(TILE, 'card transition-colors hover:border-line-strong hover:text-ink')} {...a}>
          {body}
        </a>
      ) : (
        <div className={cn(TILE, 'card')} tabIndex={0}>
          {body}
        </div>
      )}
    </Tip>
  );
}

/** Строка-ссылка таблицы: клик и Enter ведут в очередь, вложенная ссылка работает сама. */
const rowLink = (to: string) => ({
  className: 'click',
  onClick: (e: React.MouseEvent) => !(e.target as HTMLElement).closest('a, select') && go(to),
});

function Stat({ value, to, children, hint }: { value: React.ReactNode; to?: string; children: React.ReactNode; hint?: string }) {
  const body = (
    <>
      <strong className="block text-2xl font-bold">{value}</strong>
      <span className="text-[13px] text-muted">{children}</span>
    </>
  );
  return (
    <Tip content={hint}>
      {to ? (
        <a href={to} className="rounded-lg p-2 text-ink no-underline hover:bg-hover hover:text-ink">
          {body}
        </a>
      ) : (
        <div className="p-2">{body}</div>
      )}
    </Tip>
  );
}

export function Analytics() {
  const S = useS();
  const { params } = useRoute();
  const tab = (TABS as readonly string[]).includes(params.tab) ? params.tab : 'overview';
  const [saving, setSaving] = useState<Record<string, string>>({});
  const [more, setMore] = useState(false); // графики «Подробно» рисуются только в открытом блоке
  const totals: number[] = S.dialogs.map((d: any) => calc(d, S.checklist, S.appeals).total).filter((x: number | null) => x != null);
  if (!totals.length)
    return (
      <>
        <PageHead title={t('Аналитика')} />
        <Card>
          <Empty
            action={
              <LinkButton href="#/queue" variant="primary">
                {t('Перейти к диалогам')}
              </LinkButton>
            }
          >
            {t('Аналитика появится после оценки первых диалогов.')}
          </Empty>
        </Card>
      </>
    );

  const st = criteriaStats(S),
    fl = flagStats(S),
    q = qualityStats(S),
    rs = reasonsStats(S);
  const nextN = nextStepStats(S).dialogIds.length;
  const crit = (id: string) => S.checklist.criteria.find((c: any) => c.id === id);
  const dlg = (id: string) => S.dialogs.find((d: any) => d.id === id);
  // при равной доле остаётся критерий выше в чек-листе
  const dev = st.filter(x => x.n >= 3 && x.share != null).reduce((best, x) => (!best || x.share > best.share ? x : best), null);
  const top = rs.recurring[0];
  const maxR = top ? top.dialogs.length : 1;
  const flagged = fl.flaggedIds.length;
  const decidedAppeals = q.appeals.confirmed + q.appeals.changed;
  const avg = totals.length ? r2(totals.reduce((s, x) => s + x, 0) / totals.length) : null;
  const two = twoModels(S);

  const bands: Bar[] = BANDS.map(([name, lo], i) => {
    const hi = BANDS[i + 1]?.[1] ?? Infinity;
    const n = totals.filter(x => x >= lo && x < hi).length;
    return { name: i ? name : t('до 50'), value: n, label: String(n) };
  });
  const shares: Bar[] = st
    .filter(x => x.val != null)
    .map(x => {
      const share = x.type === 'scale' ? x.val / Math.max(...crit(x.cid).steps) : x.val / 100;
      return { name: `${x.cid} ${x.name}`, value: Math.round(100 * share), label: pct(share), href: lost(x.cid) };
    });
  const kinds: Bar[] = fl.kinds.map(k => ({ name: k.label, value: k.n, label: String(k.n), href: '#/queue?grp=risk' }));
  const owners = OWNERS.map(o => [o, rs.recurring.filter(g => (saving[g.tag] ?? g.owner) === o).length] as const).filter(([, n]) => n);
  const reviewsN = q.reviews.confirmed + q.reviews.changed;
  const dark = currentTheme() === 'dark';

  // Без оптимистичного обновления: до ответа селектор заблокирован и показывает выбор, при ошибке вернётся прежнее значение.
  async function setOwner(tag: string, value: string) {
    setSaving(s => ({ ...s, [tag]: value }));
    try {
      S.owners = await api.putOwners({ [tag]: value });
    } catch (e) {
      toast(t('Не сохранено, кто исправляет: {error}', { error: e.message }));
    }
    setSaving(({ [tag]: _, ...rest }) => rest);
    rerender();
  }

  return (
    <>
      <PageHead
        title={t('Аналитика')}
        sub={
          <>
            {t('Каждое число открывает список диалогов, из него карточку и реплику')}
            <span className="block text-[13px]">
              {t('В наборе {n} диалогов.', { n: S.dialogs.length })} {LANGS.map(l => `${l} ${S.dialogs.filter((d: any) => d.lang === l).length}`).join(', ')}
            </span>
          </>
        }
      >
        <LinkButton size="sm" variant="primary" href={reportUrl()} target="_blank" rel="noopener">
          <Printer size={16} aria-hidden="true" /> {t('Отчёт для руководства')}
        </LinkButton>
        <LinkButton size="sm" href={reportUrl('?format=md')} download="cqa-report.md">
          <Download size={16} aria-hidden="true" /> {t('Отчёт .md')}
        </LinkButton>
        <Tip content={t('Итог и ответы по каждому диалогу с учётом решений, как на экране.')}>
          <Button size="sm" data-act="resultscsv" onClick={() => download('cqa-results.csv', resultsCsv(S.dialogs, S.checklist, S.appeals))}>
            <Download size={16} aria-hidden="true" /> {t('Итоги CSV')}
          </Button>
        </Tip>
        <Tip content={t('Оценки для Excel с сервера: строка на диалог, ответ по каждому критерию с учётом решений.')}>
          <span>
            <DownloadButton path="/scores/export?format=csv&shape=wide" name="cqa-scores.csv" kind="scores-wide">
              <Download size={16} aria-hidden="true" /> {t('Оценки CSV')}
            </DownloadButton>
          </span>
        </Tip>
      </PageHead>

      <div role="tablist" aria-label={t('Разделы аналитики')} className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(k => (
          <a
            key={k}
            role="tab"
            aria-selected={tab === k}
            data-act="tab"
            data-tab={k}
            href={href('analytics', null, k === 'overview' ? {} : { tab: k })}
            className={cn('-mb-px whitespace-nowrap border-b-2 px-3 py-2 font-semibold no-underline', tab === k ? 'border-accent text-ink hover:text-ink' : 'border-transparent text-muted hover:text-ink')}
          >
            {tabName(k)}
          </a>
        ))}
      </div>

      {tab === 'products' ? <Products /> : tab === 'runs' ? <Runs /> : (
      <>

      <section className="lens grid grid-cols-2 gap-px overflow-hidden rounded-card border border-line bg-line shadow-card [&>*:last-child:nth-child(odd)]:col-span-2 lg:grid-cols-5 lg:[&>*:last-child:nth-child(odd)]:col-span-1" aria-label={t('Сводка')}>
        <Tile label={t('Средний итог')} value={avg == null ? '—' : f2(avg)} hint={TERMS.total}>
          {t('из 100 по {n} диалогам', { n: totals.length })}
          {totals.length < S.dialogs.length ? t(', ещё {n} ждут оценки', { n: S.dialogs.length - totals.length }) : ''}
        </Tile>
        <Tile
          href="#/queue?grp=next"
          label={t('Без решения запроса')}
          rubric={t('Качество сервиса')}
          value={nextN}
          hint={t('Группа «Без следующего шага» в очереди: клиент ушёл без решения и без понятного следующего шага.')}
        >
          {t('из {n} диалогов', { n: S.dialogs.length })}
        </Tile>
        <Tile href="#/queue?grp=risk" label={t('Грубые ошибки')} rubric={t('Контроль рисков')} value={flagged} hint={TERMS.gross}>
          {t('из {n} диалогов, проверено {r}', { n: S.dialogs.length, r: fl.reviewed })}
        </Tile>
        <Tile
          href="#/coaching"
          label={dev ? t('Теряют баллы на «{name}»', { name: dev.name }) : t('Где теряем баллы')}
          rubric={t('Развитие сотрудников')}
          value={dev ? pct(dev.share) : '—'}
          hint={t('Где теряем больше всего: критерий, на котором чаще всего снижен балл (не меньше трёх применимых оценок). Ссылка ведёт в «Обучение».')}
        >
          {dev ? t('{lost} из {n} применимых диалогов', { lost: dev.lost, n: dev.n }) : t('мало данных')}
        </Tile>
        <Tile
          href="#/analytics"
          data-act="toreasons"
          onClick={e => {
            e.preventDefault();
            document.getElementById('reasons')?.scrollIntoView({ block: 'start' });
          }}
          label={t('Повторяющаяся причина')}
          rubric={t('Улучшение процессов')}
          value={top ? top.dialogs.length : 0}
          hint={t('Самая частая повторяющаяся причина снижения. Кто её исправляет, выбирают в таблице «Повторяющиеся причины».')}
        >
          {top ? t('диалогов: {tag}', { tag: top.tag.toLowerCase() }) : t('повторяющихся причин нет')}
        </Tile>
      </section>

      <Card aria-label={t('Результат по критериям')}>
        <div className="px-4 pb-1.5 pt-4">
          <h2 className="text-base font-semibold">{t('Результат по критериям')}</h2>
          <p className="text-[13px] text-muted">
            {t('Доля считается среди применимых оценок,')} <Term k="na">N/A</Term> {t('показан отдельно. Где применимых меньше пяти, выводы ненадёжны.')}
          </p>
        </div>
        <div className="relative overflow-x-auto">
          <table className="tbl min-w-[820px]">
            <thead>
              <tr>
                <th>{t('Критерий')}</th>
                <th className="num">{t('Вес')}</th>
                <th className="num">{t('Применимо')}</th>
                <th className="num">N/A</th>
                <th className="num">{t('Результат')}</th>
                <th>{t('Теряют баллы')}</th>
                <th>
                  <span className="sr">{t('Заметки')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {st.map(x => (
                <tr key={x.cid} {...rowLink(lost(x.cid))}>
                  <td>
                    <a href={lost(x.cid)} className="text-ink no-underline hover:underline">
                      <span className="text-muted">{x.cid}</span> {x.name}
                    </a>
                  </td>
                  <td className="num">{fn(x.w)}</td>
                  <td className="num">{x.n}</td>
                  <td className="num">{x.na}</td>
                  <td className="num">{x.val == null ? '—' : x.type === 'scale' ? t('{v} из {max}', { v: fn(x.val), max: Math.max(...crit(x.cid).steps) }) : t('{p}% «Да»', { p: Math.round(x.val) })}</td>
                  <td className="whitespace-nowrap">
                    <span className="hbar inline-block h-2.5 rounded-r bg-ev align-middle" style={{ width: x.share == null ? 0 : Math.max(2, 140 * x.share) }} />{' '}
                    <span className="text-[13px]">
                      {t('{lost} из {n}', { lost: x.lost, n: x.n })}
                    </span>
                  </td>
                  <td>{x.pend ? <Chip tone="ev">{t('ждёт оценки: {n}', { n: x.pend })}</Chip> : x.n < 5 ? <Chip tone="na">{t('мало данных')}</Chip> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 items-start lg:grid-cols-2">
        <Card className="flex min-w-0 flex-col gap-3 p-4" aria-label={t('Критерий и язык')}>
          <div>
            <h2 className="text-base font-semibold">{t('Критерий и язык')}</h2>
            <p className="text-[13px] text-muted">{t('Сколько применимых диалогов потеряли баллы. В ячейке число, а не только процент: на малых выборках процент обманчив.')}</p>
          </div>
          <div className="relative overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>{t('Критерий')}</th>
                  {LANGS.map(l => (
                    <th key={l} className="num">
                      {l}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {st.map(x => (
                  <tr key={x.cid} {...rowLink(lost(x.cid))}>
                    <td>
                      <span className="text-muted">{x.cid}</span> {x.name}
                    </td>
                    {LANGS.map(l => {
                      const b = x.byLang.find(y => y.lang === l);
                      const h = b ? heat(b.lost, b.n) : 0;
                      return (
                        <td key={l} className="w-[84px] !p-1">
                          {b ? (
                            <a className={`heat hm${h} grid min-h-9 place-items-center rounded text-[13px] font-semibold no-underline`} style={heatStyle(h, dark)} href={lost(x.cid, l)}>
                              {t('{lost} из {n}', { lost: b.lost, n: b.n })}
                            </a>
                          ) : (
                            <div className="heat hm0 grid min-h-9 place-items-center rounded text-[13px]" style={heatStyle(0, dark)}>
                              —
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{t('Чем насыщеннее цвет, тем чаще теряют баллы')}</span>
            <span className="inline-flex gap-0.5" aria-hidden="true">
              {[1, 2, 3, 4].map(h => (
                <i key={h} className="h-3 w-6 rounded-sm" style={heatStyle(h, dark)} />
              ))}
            </span>
          </div>
        </Card>

        <Chart
          title={t('Грубые ошибки по видам')}
          term="gross"
          caption={t('Сколько диалогов с каждым видом грубой ошибки. Балл они не снижают, каждую нужно проверить. Проверено {n} из {total}.', { n: fl.reviewed, total: flagged })}
          rows={kinds}
          color="risk"
          action={
            <a className="text-[13px]" href="#/queue?grp=risk">
              {t('Открыть {n} в очереди', { n: flagged })}
            </a>
          }
        />
      </div>

      <Card id="reasons" aria-label={t('Повторяющиеся причины')} className="scroll-mt-20">
        <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-1.5 pt-4">
          <div>
            <h2 className="text-base font-semibold">{t('Повторяющиеся причины')}</h2>
            <p className="text-[13px] text-muted">{t('Причины снижения сгруппированы по точной формулировке. Кому их исправлять, решает человек: выберите в колонке «Кто исправляет».')}</p>
            {owners.length > 0 && (
              <p className="text-[13px] text-ink2">
                {t('Кто исправляет:')} {owners.map(([o, n]) => `${ownerName(o)}: ${n}`).join(', ')}
              </p>
            )}
          </div>
          <Button size="sm" data-act="csv" onClick={() => download('cqa-reasons.csv', reasonsCsv(S))}>
            <Download size={16} aria-hidden="true" /> {t('Скачать причины (CSV)')}
          </Button>
        </div>
        <div className="relative overflow-x-auto">
          <table className="tbl min-w-[820px]">
            <thead>
              <tr>
                <th>{t('Причина')}</th>
                <th>{t('Диалогов')}</th>
                <th>{t('Критерии')}</th>
                <th>{t('Языки')}</th>
                <th>{t('Кто исправляет')}</th>
                <th>{t('Примеры')}</th>
              </tr>
            </thead>
            <tbody>
              {rs.recurring.length ? (
                rs.recurring.map((g, k) => (
                  <tr key={g.tag}>
                    <td className="font-semibold">{g.tag}</td>
                    <td className="whitespace-nowrap">
                      <span className="hbar inline-block h-2.5 rounded-r bg-ev align-middle" style={{ width: (80 * g.dialogs.length) / maxR }} /> <b>{g.dialogs.length}</b>
                    </td>
                    <td>{g.criteria.join(', ')}</td>
                    <td>{g.langs.join(', ')}</td>
                    <td>
                      <label className="sr" htmlFor={`own${k}`}>
                        {t('Кто исправляет: {tag}', { tag: g.tag })}
                      </label>
                      <select
                        id={`own${k}`}
                        className="fld"
                        data-act="owner"
                        data-tag={g.tag}
                        value={saving[g.tag] ?? g.owner}
                        disabled={g.tag in saving}
                        onChange={e => setOwner(g.tag, e.target.value)}
                      >
                        {OWNERS.map(o => (
                          <option key={o} value={o}>
                            {ownerName(o)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="text-[13px]">
                      {g.dialogs.slice(0, 3).map((id, i) => (
                        <span key={id}>
                          {i > 0 && ', '}
                          <a href={href('d', id)}>{titleOf(dlg(id))}</a>
                        </span>
                      ))}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-muted">
                    {t('Повторяющихся причин нет.')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {rs.single ? <p className="px-4 pb-4 text-[13px] text-muted">{t('Ещё {n} причин встретились по одному разу. Они видны в карточках и в разделе «Обучение».', { n: rs.single })}</p> : null}
      </Card>

      <details onToggle={e => setMore(e.currentTarget.open)}>
        <summary className="cursor-pointer py-1 text-base font-semibold">{t('Подробно: распределение итогов, доля баллов, качество самой оценки')}</summary>
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          {more && (
            <>
              <Chart
                title={t('Распределение итогов')}
                caption={totals.length < S.dialogs.length ? t('Сколько диалогов получили итог в каждом диапазоне; без итога: {n}.', { n: S.dialogs.length - totals.length }) : t('Сколько диалогов получили итог в каждом диапазоне.')}
                rows={bands}
                vertical
              />
              <Chart title={t('Доля баллов по критериям')} caption={t('Сколько баллов от максимума набрано среди применимых оценок; при 100% у всех полный балл.')} rows={shares} />
            </>
          )}
          {/* в DOM всегда: текст блока ищут тесты и диктор, графики выше рисуются только в открытом блоке */}
          <Card className="flex flex-col gap-3 p-4 lg:col-span-2" aria-label={t('Качество самой оценки')}>
          <div>
            <h2 className="text-base font-semibold">{t('Качество самой оценки')}</h2>
            <p className="text-[13px] text-muted">{t('Можно ли доверять оценке: как часто люди меняют ответы модели.')}</p>
          </div>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {two && (
              <Stat to="#/queue?grp=review" value={q.answers ? `${Math.round((100 * q.agree) / q.answers)}%` : '—'} hint={TERMS.second}>
                {t('ответов: второе мнение совпало ({agree} из {n})', { agree: q.agree, n: q.answers })}
              </Stat>
            )}
            <Stat to="#/queue?grp=review" value={q.evFail}>
              {two ? t('ответов не подтверждены цитатой из диалога') : t('ответов не подтверждены цитатой из диалога; второе мнение выключено')}
            </Stat>
            <Stat to="#/queue?grp=review" value={q.awaiting} hint={TERMS.review}>
              {t('ответов: нужна проверка человека')}
            </Stat>
            {decidedAppeals > 0 && (
              <Stat to="#/appeals" value={t('{lost} из {n}', { lost: q.appeals.changed, n: decidedAppeals })} hint={TERMS.appeal}>
                {t('решённых апелляций изменили оценку; ждут {pending}, закрыто новой версией {closed}', { pending: q.appeals.pending, closed: q.appeals.closed })}
              </Stat>
            )}
            {reviewsN > 0 && <Stat value={t('{lost} из {n}', { lost: q.reviews.changed, n: reviewsN })}>{t('решений специалиста по расхождениям моделей изменили ответ')}</Stat>}
          </div>
          {!decidedAppeals && !reviewsN && (
            <p className="text-[13px] text-muted">
              {q.appeals.pending ? (
                <a href="#/appeals">{t('Решений пока нет, апелляций ждут решения: {n}.', { n: q.appeals.pending })}</a>
              ) : (
                t('Апелляций и решений пока нет.')
              )}
            </p>
          )}
          {q.byCriterion.length > 0 && (
            <>
              <h3 className="text-[13px] font-semibold text-muted">{t('Где модель расходится с людьми')}</h3>
              <div className="relative overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>{t('Критерий')}</th>
                      <th>{t('Язык')}</th>
                      <th className="num">{t('Решено')}</th>
                      <th className="num">{t('Изменено')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.byCriterion.map(x => (
                      <tr key={`${x.cid}|${x.lang}`} {...rowLink(lost(x.cid, x.lang))} tabIndex={0} onKeyDown={e => e.key === 'Enter' && go(lost(x.cid, x.lang))}>
                        <td>
                          <span className="text-muted">{x.cid}</span> {crit(x.cid)?.name ?? ''}
                        </td>
                        <td>{x.lang}</td>
                        <td className="num">{x.decided}</td>
                        <td className="num">{x.changed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
        </div>
      </details>
      {S.role !== 'operator' && <Recommendations kind="manager" title={t('Рекомендации руководителю')} />}
      </>
      )}
    </>
  );
}
