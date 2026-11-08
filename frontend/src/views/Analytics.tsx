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
import { api, toast } from '../lib/state.js';
import { go, rerender, useS } from '../store';
import { Term, TERMS } from '../terms';
import { Button, Card, Chip, cn, Empty, LinkButton, PageHead, Tip } from '../ui';
import { Chart, type Bar } from './analytics/Chart';

const LANGS = ['RU', 'KZ', 'EN'];
const OWNERS = ['Не назначено', 'Инструкция', 'Сервис', 'Продукт'];
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
const heatStyle = (h: number) => ({ background: HEAT_BG[h], color: h === 4 ? 'var(--surface)' : h ? 'var(--ink)' : 'var(--muted)' });

function download(name: string, text: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

// Отчёт для руководства (GET {api}/report): адрес API тот же, что у main.tsx; фильтров на экране нет, параметры не нужны.
const reportUrl = (fmt = '') => `${resolveBase(location.search, document.querySelector<HTMLElement>('cqa-app')?.dataset.api)}/report${fmt}`;

const TILE = 'flex min-w-0 flex-col gap-1.5 rounded-card border border-line bg-surface px-4 py-3.5 text-ink no-underline shadow-card';

/** Плитка сводки: число в <strong>, подпись и пояснение; со ссылкой — <a>, иначе <div>. */
function Tile({ label, value, hint, children, ...a }: { label: string; value: React.ReactNode; hint: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const body = (
    <>
      <span className="text-[13px] font-semibold text-muted">{label}</span>
      <strong className="text-[28px] font-bold leading-tight">{value}</strong>
      <span className="text-[13px] text-ink2">{children}</span>
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
  const [saving, setSaving] = useState<Record<string, string>>({});
  const totals: number[] = S.dialogs.map((d: any) => calc(d, S.checklist, S.appeals).total).filter((t: number | null) => t != null);
  if (!totals.length)
    return (
      <>
        <PageHead title="Аналитика" />
        <Card>
          <Empty
            action={
              <LinkButton href="#/queue" variant="primary">
                Перейти к диалогам
              </LinkButton>
            }
          >
            Аналитика появится после оценки первых диалогов.
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
  const avg = totals.length ? r2(totals.reduce((s, t) => s + t, 0) / totals.length) : null;
  const two = twoModels(S);

  const bands: Bar[] = BANDS.map(([name, lo], i) => {
    const hi = BANDS[i + 1]?.[1] ?? Infinity;
    const n = totals.filter(t => t >= lo && t < hi).length;
    return { name, value: n, label: String(n) };
  });
  const shares: Bar[] = st
    .filter(x => x.val != null)
    .map(x => {
      const share = x.type === 'scale' ? x.val / Math.max(...crit(x.cid).steps) : x.val / 100;
      return { name: `${x.cid} ${x.name}`, value: Math.round(100 * share), label: pct(share), href: lost(x.cid) };
    });
  const kinds: Bar[] = fl.kinds.map(k => ({ name: k.label, value: k.n, label: String(k.n), href: '#/queue?grp=risk' }));
  const owners: Bar[] = OWNERS.map(o => {
    const n = new Set(rs.recurring.filter(g => (saving[g.tag] ?? g.owner) === o).flatMap(g => g.dialogs)).size;
    return { name: o, value: n, label: String(n) };
  });

  // Без оптимистичного обновления: до ответа селектор заблокирован и показывает выбор, при ошибке вернётся прежнее значение.
  async function setOwner(tag: string, value: string) {
    setSaving(s => ({ ...s, [tag]: value }));
    try {
      S.owners = await api.putOwners({ [tag]: value });
    } catch (e) {
      toast(`Не сохранено, кто исправляет: ${e.message}`);
    }
    setSaving(({ [tag]: _, ...rest }) => rest);
    rerender();
  }

  return (
    <>
      <PageHead title="Аналитика" sub="Каждое число открывает список диалогов, из него карточку и реплику">
        <span className="text-[13px] text-muted">
          В наборе {S.dialogs.length} диалогов. {LANGS.map(l => `${l} ${S.dialogs.filter((d: any) => d.lang === l).length}`).join(', ')}
        </span>
        <LinkButton size="sm" href={reportUrl()} target="_blank" rel="noopener">
          <Printer size={16} aria-hidden="true" /> Отчёт для руководства
        </LinkButton>
        <LinkButton size="sm" href={reportUrl('?format=md')} download="cqa-report.md">
          <Download size={16} aria-hidden="true" /> Скачать .md
        </LinkButton>
        <Button size="sm" data-act="resultscsv" onClick={() => download('cqa-results.csv', resultsCsv(S.dialogs, S.checklist, S.appeals))}>
          <Download size={16} aria-hidden="true" /> Скачать итоги по диалогам (CSV)
        </Button>
      </PageHead>

      <section className="lens grid grid-cols-2 gap-3 lg:grid-cols-5" aria-label="Сводка">
        <Tile label="Средний итог" value={avg == null ? '—' : f2(avg)} hint={TERMS.total}>
          из 100 по {totals.length} диалогам{totals.length < S.dialogs.length ? `, ещё ${S.dialogs.length - totals.length} ждут оценки` : ''}
        </Tile>
        <Tile href="#/queue?grp=next" label="Качество сервиса" value={nextN} hint="Группа «Без следующего шага» в очереди: клиент ушёл без решения и без понятного следующего шага.">
          {nextN === 1 ? 'запрос остался' : 'запросов остались'} без решения или понятного следующего шага
        </Tile>
        <Tile href="#/queue?grp=risk" label="Контроль рисков" value={flagged} hint={TERMS.gross}>
          диалогов с грубыми ошибками, проверено {fl.reviewed}
        </Tile>
        <Tile
          href="#/coaching"
          label="Развитие сотрудников"
          value={dev ? pct(dev.share) : '—'}
          hint="Где теряем больше всего: критерий, на котором чаще всего снижен балл (не меньше трёх применимых оценок). Ссылка ведёт в «Обучение»."
        >
          {dev ? `применимых диалогов (${dev.lost} из ${dev.n}) теряют баллы на критерии «${dev.name}»` : 'мало данных'}
        </Tile>
        <Tile
          href="#/analytics"
          data-act="toreasons"
          onClick={e => {
            e.preventDefault();
            document.getElementById('reasons')?.scrollIntoView({ block: 'start' });
          }}
          label="Улучшение процессов"
          value={top ? top.dialogs.length : 0}
          hint="Самая частая повторяющаяся причина снижения. Кто её исправляет, выбирают в таблице «Повторяющиеся причины»."
        >
          {top ? `диалогов с одной причиной: ${top.tag.toLowerCase()}` : 'повторяющихся причин нет'}
        </Tile>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Chart
          title="Распределение итогов"
          caption={`Сколько диалогов получили итог в каждом диапазоне${totals.length < S.dialogs.length ? `; без итога: ${S.dialogs.length - totals.length}` : ''}.`}
          rows={bands}
          vertical
        />
        <Chart title="Доля баллов по критериям" caption="Сколько баллов от максимума набрано среди применимых оценок; при 100% у всех полный балл." rows={shares} />
      </div>

      <Card aria-label="Результат по критериям">
        <div className="px-4 pb-1.5 pt-4">
          <h2 className="text-base font-semibold">Результат по критериям</h2>
          <p className="text-[13px] text-muted">
            Доля считается среди применимых оценок, <Term k="na">N/A</Term> показан отдельно. Где применимых меньше пяти, выводы ненадёжны.
          </p>
        </div>
        <div className="relative overflow-x-auto">
          <table className="tbl min-w-[820px]">
            <thead>
              <tr>
                <th>Критерий</th>
                <th className="num">Вес</th>
                <th className="num">Применимо</th>
                <th className="num">N/A</th>
                <th className="num">Результат</th>
                <th>Теряют баллы</th>
                <th>
                  <span className="sr">Заметки</span>
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
                  <td className="num">{x.val == null ? '—' : x.type === 'scale' ? `${fn(x.val)} из ${Math.max(...crit(x.cid).steps)}` : `${Math.round(x.val)}% «Да»`}</td>
                  <td className="whitespace-nowrap">
                    <span className="hbar inline-block h-2.5 rounded-r bg-ev align-middle" style={{ width: x.share == null ? 0 : Math.max(2, 140 * x.share) }} />{' '}
                    <span className="text-[13px]">
                      {x.lost} из {x.n}
                    </span>
                  </td>
                  <td>{x.pend ? <Chip tone="ev">ждёт оценки: {x.pend}</Chip> : x.n < 5 ? <Chip tone="na">мало данных</Chip> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="flex min-w-0 flex-col gap-3 p-4" aria-label="Критерий и язык">
          <div>
            <h2 className="text-base font-semibold">Критерий и язык</h2>
            <p className="text-[13px] text-muted">Сколько применимых диалогов потеряли баллы. В ячейке число, а не только процент: на малых выборках процент обманчив.</p>
          </div>
          <div className="relative overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Критерий</th>
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
                            <a className={`heat hm${h} grid min-h-9 place-items-center rounded text-[13px] font-semibold no-underline`} style={heatStyle(h)} href={lost(x.cid, l)}>
                              {b.lost} из {b.n}
                            </a>
                          ) : (
                            <div className="heat hm0 grid min-h-9 place-items-center rounded text-[13px]" style={heatStyle(0)}>
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
            <span>Доля диалогов, потерявших баллы: светлее реже</span>
            <span className="inline-flex gap-0.5" aria-hidden="true">
              {[1, 2, 3, 4].map(h => (
                <i key={h} className="h-3 w-6 rounded-sm" style={heatStyle(h)} />
              ))}
            </span>
          </div>
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          <Chart
            title="Грубые ошибки по видам"
            term="gross"
            caption={`Сколько диалогов с каждым видом грубой ошибки. Балл они не снижают, каждую нужно проверить. Проверено ${fl.reviewed} из ${flagged}.`}
            rows={kinds}
            color="risk"
            action={
              <a className="text-[13px]" href="#/queue?grp=risk">
                Открыть {flagged} в очереди
              </a>
            }
          />
          <Card className="flex flex-col gap-3 p-4" aria-label="Качество самой оценки">
            <div>
              <h2 className="text-base font-semibold">Качество самой оценки</h2>
              <p className="text-[13px] text-muted">Можно ли доверять оценке: как часто люди меняют ответы модели.</p>
            </div>
            <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {two && (
                <Stat to="#/queue?grp=review" value={q.answers ? `${Math.round((100 * q.agree) / q.answers)}%` : '—'} hint={TERMS.second}>
                  ответов: второе мнение совпало ({q.agree} из {q.answers})
                </Stat>
              )}
              <Stat to="#/queue?grp=review" value={q.evFail}>
                ответов не подтверждены цитатой из диалога{two ? '' : '; второе мнение выключено'}
              </Stat>
              <Stat to="#/queue?grp=review" value={q.awaiting} hint={TERMS.review}>
                ответов: нужна проверка человека
              </Stat>
              <Stat to="#/appeals" value={`${q.appeals.changed} из ${decidedAppeals}`} hint={TERMS.appeal}>
                решённых апелляций изменили оценку; ждут {q.appeals.pending}, закрыто новой версией {q.appeals.closed}
              </Stat>
              <Stat value={`${q.reviews.changed} из ${q.reviews.confirmed + q.reviews.changed}`}>решений специалиста по расхождениям моделей изменили ответ</Stat>
            </div>
            <h3 className="text-[13px] font-semibold text-muted">Где модель расходится с людьми</h3>
            {q.byCriterion.length ? (
              <div className="relative overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Критерий</th>
                      <th>Язык</th>
                      <th className="num">Решено</th>
                      <th className="num">Изменено</th>
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
            ) : (
              <p className="text-[13px] text-muted">Решений пока нет.</p>
            )}
          </Card>
        </div>
      </div>

      <Chart title="Кто исправляет причины" caption="Сколько диалогов с повторяющимися причинами у каждого, кто исправляет. Выбор в таблице «Повторяющиеся причины»." rows={owners} color="ev" />

      <Card id="reasons" aria-label="Повторяющиеся причины" className="scroll-mt-20">
        <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-1.5 pt-4">
          <div>
            <h2 className="text-base font-semibold">Повторяющиеся причины</h2>
            <p className="text-[13px] text-muted">Причины снижения сгруппированы по точной формулировке. Кому их исправлять, решает человек: выберите в колонке «Кто исправляет».</p>
          </div>
          <Button size="sm" data-act="csv" onClick={() => download('cqa-reasons.csv', reasonsCsv(S))}>
            <Download size={16} aria-hidden="true" /> Скачать причины (CSV)
          </Button>
        </div>
        <div className="relative overflow-x-auto">
          <table className="tbl min-w-[820px]">
            <thead>
              <tr>
                <th>Причина</th>
                <th>Диалогов</th>
                <th>Критерии</th>
                <th>Языки</th>
                <th>Кто исправляет</th>
                <th>Примеры</th>
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
                        Кто исправляет: {g.tag}
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
                          <option key={o}>{o}</option>
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
                    Повторяющихся причин нет.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {rs.single ? <p className="px-4 pb-4 text-[13px] text-muted">Ещё {rs.single} причин встретились по одному разу. Они видны в карточках и в разделе «Обучение».</p> : null}
      </Card>
    </>
  );
}
