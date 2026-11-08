// Экран очереди: группы приоритета, плитки-фильтры из хеша, поиск, добавление диалогов и панель оценки.
// Роли: загрузка, оценка и цена только у специалиста КК; оператор не видит «Нужна проверка человека» и второе мнение.
import { Search, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { ansTxt, f2, titleOf } from '../lib/format.js';
import { byJev, reasonOf, syncNote, twoModels } from '../lib/queue.js';
import { href } from '../lib/router.js';
import { ans, flagsOf, flagWhy, r2 } from '../lib/scoring.js';
import { go, rerender, useRoute, useS } from '../store';
import { TERMS } from '../terms';
import { Button, Chip, cn, PageHead, Tip, type Tone } from '../ui';
import { AddMenu, JsonInput } from './queue/AddMenu';
import { DIALOGS, hasFilters, plural, rowsOf, visibleRows, type Row } from './queue/order';
import { RunPanel } from './queue/RunPanel';

const cut = (s: string, n = 140) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);

// Подсказка группы зависит от второго мнения: без него о двух моделях не говорим.
const GROUPS: [string, string, Tone, (two: boolean) => string][] = [
  ['risk', 'Грубые ошибки', 'risk', two => `Находит модель${two ? ' или второе мнение' : ''}. Итог они не снижают.`],
  ['review', 'Нужна проверка человека', 'info', two => (two ? 'Второе мнение не совпало или ответ не подтверждён цитатой.' : 'Ответ не подтверждён цитатой из диалога.')],
  ['next', 'Без понятного следующего шага', 'ev', () => 'Критерий с сигналом «Решение запроса» ниже верхней ступени.'],
  ['other', 'Остальные', 'na', () => ''],
];
const TONE: Record<string, Tone> = { 'c-risk': 'risk', 'c-info': 'info', 'c-ev': 'ev', 'c-na': 'na', 'c-ok': 'ok' };

const setParam = (params: Record<string, string>, k: string, v: string) => href('queue', null, { ...params, [k]: v });

/** Причина первой найденной грубой ошибки и её реплика: flagWhy по вопросам флага. */
function grossWhy(d: any, cl: any, ap: any): { why: string; n?: number } | null {
  for (const fc of cl.criteria) {
    const a = fc.type === 'flag' ? ans(d, fc.id, ap) : null;
    if (!a || !d.res[fc.id]) continue;
    const w = flagWhy(fc, d.res[fc.id]);
    const x = w.qs.find((x: any) => a[x.q.k]);
    if (x) return { why: x.why || w.rest, n: x.ev[0] ?? w.ev[0] };
  }
  return null;
}

function Tile(p: { title: string; tip?: string; n: ReactNode; zero?: boolean; unit?: string; note: ReactNode; pressed?: boolean; onClick?: () => void; to?: string; g?: string }) {
  const cls = cn(
    'tile flex min-w-0 flex-col items-start gap-0.5 rounded-card border p-3.5 text-left no-underline shadow-card transition-colors hover:border-line-strong',
    p.pressed ? 'border-accent bg-accent-soft' : 'border-line bg-surface',
  );
  const inner = (
    <>
      <span className={cn('text-[13px] font-semibold text-ink2', p.tip && 'underline decoration-line-strong decoration-dotted underline-offset-[3px]')}>{p.title}</span>
      <span className={cn('text-[28px] font-bold leading-tight', p.zero ? 'text-muted' : 'text-ink')}>
        {p.n}
        {p.unit && <span className="ml-1 text-sm font-normal text-muted">{p.unit}</span>}
      </span>
      <span className="text-xs text-muted">{p.note}</span>
    </>
  );
  return (
    <Tip content={p.tip}>
      {p.to ? (
        <a className={cls} href={p.to}>
          {inner}
        </a>
      ) : (
        <button type="button" className={cls} data-act="grp" data-g={p.g} aria-pressed={p.pressed} onClick={p.onClick}>
          {inner}
        </button>
      )}
    </Tip>
  );
}

function Status({ d, c }: { d: any; c: any }) {
  const S = useS();
  if (c.pending) return <Chip tone="ev">Ждёт оценки</Chip>;
  if (S.appeals.some((a: any) => a.dlg === d.id && a.status === 'pending')) return <Chip tone="info">Апелляция</Chip>;
  return d.reviewed ? <Chip tone="ok">Проверен</Chip> : null;
}

/** «Почему в очереди»: чип причины; у грубой ошибки ещё причина модели и ссылка на реплику. */
function Why({ x, op }: { x: Row; op: boolean }) {
  const S = useS();
  if (op && x.g === 'review') return null; // оператор не видит «Нужна проверка человека»
  const why = reasonOf(x.d, S.checklist, S.appeals);
  if (!why.text) return null;
  const chip = <Chip tone={TONE[why.cls] ?? 'na'} className="!whitespace-normal md:!whitespace-nowrap">{why.text}</Chip>;
  if (x.g === 'review') {
    // в тексте причины номер критерия: подсказка с названием
    const c = S.checklist.criteria.find((c: any) => c.id === why.text.match(/\b\d{2}\b/)?.[0]);
    return c ? (
      <Tip content={`${c.id} ${c.name}`}>
        <span tabIndex={0}>{chip}</span>
      </Tip>
    ) : (
      chip
    );
  }
  const g = x.g === 'risk' ? grossWhy(x.d, S.checklist, S.appeals) : null;
  if (!g?.why && g?.n == null) return chip;
  const short = cut(g.why || '');
  return (
    <div className="flex flex-col items-start gap-1">
      {chip}
      <span className="line-clamp-3 text-xs text-muted md:line-clamp-none">
        {g.n != null && (
          <a href={href('d', x.d.id, { n: String(g.n) })} className="font-semibold">
            Реплика {g.n}
          </a>
        )}
        {g.n != null && short && ': '}
        {short !== g.why ? (
          <Tip content={g.why}>
            <span tabIndex={0}>{short}</span>
          </Tip>
        ) : (
          short
        )}
      </span>
    </div>
  );
}

export function Queue() {
  const S = useS();
  const { params: p } = useRoute();
  const qa = S.role === 'qa',
    op = S.role === 'operator';
  const cl = S.checklist,
    ap = S.appeals;
  const all = rowsOf();
  const cnt = (g: string) => all.filter(x => x.g === g).length;
  const totals = all.map(x => x.c.total).filter(x => x != null);
  const avg = totals.length ? r2(totals.reduce((a, b) => a + b, 0) / totals.length) : null;
  const two = twoModels(S);
  const seq = visibleRows(p);
  const filtered = hasFilters(p);
  const flagged = S.dialogs.filter((d: any) => flagsOf(d, cl, ap).length);
  const checked = flagged.filter((d: any) => d.reviewed).length;
  // оператору группа «Нужна проверка человека» не показывается: её строки идут в «Остальные»
  const shown = (g: string) => (op && g === 'review' ? 'other' : g);
  const toggle = (g: string) => go(setParam(p, 'grp', p.grp === g ? '' : g));
  const clear = () => {
    S.q = '';
    go(href('queue'));
    rerender();
  };
  const sel = (id: string, label: string, k: string, vals: [string, string][]) => (
    <label className="flex items-center gap-2 text-[13px] text-muted">
      {label}
      <select id={id} className="fld" data-act={id} value={p[k] || ''} onChange={e => go(setParam(p, k, e.target.value))}>
        {vals.map(([v, t]) => (
          <option key={v} value={v}>
            {t}
          </option>
        ))}
      </select>
    </label>
  );
  const sub = qa ? 'Сначала диалоги с грубыми ошибками и спорными ответами модели' : 'Оценки диалогов по чек-листу. Откройте диалог, чтобы увидеть, за что снижен балл.';

  if (!S.dialogs.length)
    return (
      <>
        <PageHead title="Диалоги" sub={sub} />
        {qa && S.run && <RunPanel all={all} dialogs={null} pending={0} />}
        <section className="flex flex-col items-start gap-3 rounded-card border border-line bg-surface p-5 shadow-card" aria-label="Список диалогов">
          <p className="text-muted">{qa ? 'Диалогов пока нет. Загрузите набор или вставьте диалог текстом.' : 'Диалогов пока нет. Их загружает специалист КК.'}</p>
          {qa && <AddMenu primary />}
        </section>
        {qa && <JsonInput />}
      </>
    );

  const target = filtered ? seq : all;
  return (
    <>
      <PageHead title="Диалоги" sub={sub}>
        {qa && <AddMenu />}
      </PageHead>
      {qa && <JsonInput />}
      {qa && S.source && <p className="text-[13px] text-muted">{syncNote(S.source)}</p>}
      {qa && <RunPanel all={all} dialogs={filtered ? seq.map(x => x.d.id) : null} pending={target.filter(x => x.c.pending).length} />}

      <section className={cn('grid grid-cols-2 gap-3 md:grid-cols-3', op ? 'xl:grid-cols-4' : 'xl:grid-cols-5')} aria-label="Быстрые фильтры">
        <Tile
          title="Грубые ошибки"
          tip={TERMS.gross}
          n={cnt('risk')}
          zero={!cnt('risk')}
          note={`не проверено: ${cnt('risk')}${checked ? `, проверено: ${checked}` : ''}`}
          pressed={p.grp === 'risk'}
          onClick={() => toggle('risk')}
          g="risk"
        />
        {!op && (
          <Tile
            title="Нужна проверка человека"
            tip={byJev(S.mode) ? TERMS.jevUnsure : TERMS.review}
            n={cnt('review')}
            zero={!cnt('review')}
            note={byJev(S.mode) ? 'Jev не уверен в ответе' : two ? 'второе мнение не совпало или нет цитаты' : 'ответ не подтверждён цитатой'}
            pressed={p.grp === 'review'}
            onClick={() => toggle('review')}
            g="review"
          />
        )}
        <Tile title="Без следующего шага" n={cnt('next')} zero={!cnt('next')} note="следующий шаг не назван или неполный" pressed={p.grp === 'next'} onClick={() => toggle('next')} g="next" />
        <Tile title="Апелляции ждут решения" tip={TERMS.appeal} n={ap.filter((a: any) => a.status === 'pending').length} zero={!ap.some((a: any) => a.status === 'pending')} note="решает проверяющий" to={href('appeals')} />
        <Tile title="Средний итог" tip={TERMS.total} n={f2(avg)} unit={avg != null ? 'из 100' : undefined} note={`по ${totals.length} ${totals.length % 10 === 1 && totals.length % 100 !== 11 ? 'диалогу' : 'диалогам'}, открыть аналитику`} to={href('analytics')} />
      </section>

      {p.grp === 'risk' && (
        <p className="text-ink2">
          <b className="text-ink">
            Грубые ошибки: {cnt('risk')} {plural(cnt('risk'), DIALOGS)}.
          </b>{' '}
          Балл они не снижают, каждую нужно проверить. Проверено {checked} из {flagged.length}.
        </p>
      )}

      <section className="rounded-card border border-line bg-surface shadow-card" aria-label="Список диалогов">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-3.5 py-3">
          <label className="relative flex min-w-0 flex-[1_1_220px] items-center">
            <span className="sr">Поиск</span>
            <Search size={16} className="pointer-events-none absolute left-2.5 text-muted" aria-hidden="true" />
            <input
              id="q"
              className="fld w-full pl-8"
              placeholder="Номер диалога или текст реплики"
              value={S.q}
              onChange={e => {
                S.q = e.target.value;
                rerender();
              }}
            />
            <kbd className="pointer-events-none absolute right-2.5 rounded border border-line px-1 text-[11px] text-muted [@media(pointer:coarse)]:hidden">/</kbd>
          </label>
          {sel('fl', 'Язык', 'lang', [
            ['', 'Все'],
            ['RU', 'RU'],
            ['KZ', 'KZ'],
            ['EN', 'EN'],
          ])}
          {sel('fc', 'Канал', 'ch', [
            ['', 'Все'],
            ['chat', 'Чат'],
            ['call', 'Звонок'],
          ])}
          {filtered && (
            <Button size="sm" data-act="clear" onClick={clear}>
              <X size={16} aria-hidden="true" /> Сбросить фильтры
            </Button>
          )}
        </div>
        {!seq.length ? (
          <div className="flex flex-col items-start gap-3 p-5">
            <p className="text-muted">Под эти фильтры ничего не подходит.</p>
            <Button onClick={clear}>Сбросить фильтры</Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl md:min-w-[860px]">
              <thead>
                <tr>
                  <th>Диалог</th>
                  <th className="hidden md:table-cell">Канал и язык</th>
                  <th className="num !text-right">Итог</th>
                  <th>Почему в очереди</th>
                  <th className="hidden md:table-cell">Где потеряны баллы</th>
                  <th className="hidden md:table-cell">Статус</th>
                </tr>
              </thead>
              {GROUPS.map(([g, title, tone, hint]) => {
                if (op && g === 'review') return null;
                const rs = seq.filter(x => shown(x.g) === g);
                if (!rs.length) return null;
                return (
                  <tbody key={g}>
                    <tr className="grp">
                      <td colSpan={6}>
                        <Chip tone={tone} className="chip">
                          {title}: {rs.length}
                        </Chip>
                        {hint(two) && <span className="ml-2 text-xs font-normal text-muted">{hint(two)}</span>}
                      </td>
                    </tr>
                    {rs.map(x => (
                      <tr
                        key={x.d.id}
                        className={cn('click align-top', x.d.id === S.qsel && 'sel')}
                        data-act="open"
                        data-id={x.d.id}
                        onClick={e => {
                          if (!(e.target as Element).closest('a')) go(href('d', x.d.id));
                        }}
                      >
                        <td>
                          <a href={href('d', x.d.id)} className="whitespace-nowrap font-semibold no-underline">
                            {titleOf(x.d)}
                          </a>
                          <span className="block text-xs text-muted md:hidden">
                            {x.d.ch === 'call' ? 'Звонок' : 'Чат'}, {x.d.lang}
                          </span>
                        </td>
                        <td className="hidden md:table-cell">
                          {x.d.ch === 'call' ? 'Звонок' : 'Чат'}, {x.d.lang}
                        </td>
                        <td className="num font-bold">{f2(x.c.total)}</td>
                        <td>
                          <Why x={x} op={op} />
                        </td>
                        <td className="hidden text-[13px] text-muted md:table-cell">
                          {x.c.losses
                            .slice(0, 3)
                            .map((r: any) => `${r.c.name}: ${ansTxt(r.c, r.a)}`)
                            .join(' · ') || '—'}
                        </td>
                        <td className="hidden md:table-cell">
                          <Status d={x.d} c={x.c} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                );
              })}
            </table>
          </div>
        )}
      </section>
      <p className="text-xs text-muted [@media(pointer:coarse)]:hidden">
        Клавиши <kbd className="rounded border border-line px-1">J</kbd> и <kbd className="rounded border border-line px-1">K</kbd> перемещаются по списку,{' '}
        <kbd className="rounded border border-line px-1">Enter</kbd> открывает карточку, <kbd className="rounded border border-line px-1">/</kbd> ставит курсор в поиск.
      </p>
    </>
  );
}
