// Экран очереди: группы приоритета, плитки-фильтры из хеша, поиск, загрузка набора и панель оценки.
// Действия специалиста КК (набор, вставка, оценка) у оператора и проверяющего скрыты, как .only-qa в прежнем интерфейсе.
import { ClipboardPaste, Download, FileUp, Search, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { ansTxt, f2, titleOf } from '../lib/format.js';
import { byJev, groupOf, reasonOf, syncNote, twoModels } from '../lib/queue.js';
import { href } from '../lib/router.js';
import { calc, flagsOf, r2 } from '../lib/scoring.js';
import { postDataset, saveSource, uploadDataset } from '../lib/state.js';
import { go, rerender, useRoute, useS } from '../store';
import { Button, Chip, cn, Empty, PageHead, type Tone } from '../ui';
import { openPaste } from './PasteDialog';
import { hasFilters, visibleRows, type Row } from './queue/order';
import { RunPanel } from './queue/RunPanel';

// Подсказка группы зависит от второго мнения: без него о двух моделях не говорим.
const GROUPS: [string, string, Tone, (two: boolean) => string][] = [
  ['risk', 'Грубые ошибки', 'risk', two => `флаг ставит ${two ? 'любая из двух моделей' : 'модель'}, итог он не обнуляет`],
  ['review', 'Нужна проверка человека', 'info', two => `${two ? 'модели разошлись или ' : ''}цитата не нашлась в реплике`],
  ['next', 'Без понятного следующего шага', 'ev', () => 'критерий с сигналом «Решение запроса» ниже верхней ступени'],
  ['other', 'Остальные', 'na', () => ''],
];
const TONE: Record<string, Tone> = { 'c-risk': 'risk', 'c-info': 'info', 'c-ev': 'ev', 'c-na': 'na', 'c-ok': 'ok' };

const setParam = (params: Record<string, string>, k: string, v: string) => href('queue', null, { ...params, [k]: v });

function Tile({ title, n, note, pressed, onClick, to, g }: { title: string; n: React.ReactNode; note: string; pressed?: boolean; onClick?: () => void; to?: string; g?: string }) {
  const cls = cn(
    'tile flex min-w-0 flex-col items-start gap-0.5 rounded-card border bg-surface p-3.5 text-left no-underline shadow-card transition-colors hover:border-line-strong',
    pressed ? 'border-accent bg-accent-soft' : 'border-line',
  );
  const inner = (
    <>
      <span className="text-[13px] font-semibold text-ink2">{title}</span>
      <strong className="num text-2xl font-bold text-ink">{n}</strong>
      <span className="text-xs text-muted">{note}</span>
    </>
  );
  return to ? (
    <a className={cls} href={to}>
      {inner}
    </a>
  ) : (
    <button type="button" className={cls} data-act="grp" data-g={g} aria-pressed={pressed} onClick={onClick}>
      {inner}
    </button>
  );
}

function Status({ d, c }: { d: any; c: any }) {
  const S = useS();
  if (c.pending) return <Chip tone="ev">Ждёт оценки</Chip>;
  if (S.appeals.some((a: any) => a.dlg === d.id && a.status === 'pending')) return <Chip tone="info">Апелляция</Chip>;
  return d.reviewed ? <Chip tone="ok">Проверен</Chip> : <Chip tone="na">Не проверен</Chip>;
}

function DatasetActions() {
  const gid = useRef<HTMLInputElement>(null);
  const url = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true);
    const u = url.current.value.trim();
    // ссылка сохраняется на сервере и включает автосинхронизацию
    await (u ? saveSource(u, gid.current.value) : postDataset(gid.current.value));
    setBusy(false);
  };
  return (
    <>
      <label className="sr" htmlFor="gid">
        Набор по group_id
      </label>
      <input id="gid" className="fld w-[110px]" defaultValue="DEV" ref={gid} title="group_id набора у организаторов" />
      <label className="sr" htmlFor="orgurl">
        Ссылка API организаторов
      </label>
      <input id="orgurl" ref={url} type="url" className="fld w-[240px] max-w-full" placeholder="Ссылка API организаторов" autoComplete="off" title="Необязательно. Со ссылкой набор синхронизируется раз в 5 минут" />
      <Button data-act="load" onClick={load} disabled={busy}>
        <Download size={16} aria-hidden="true" /> {busy ? 'Получаем…' : 'Получить набор'}
      </Button>
      <label htmlFor="jsonf" className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border border-line-strong bg-surface px-3.5 font-semibold text-ink hover:bg-hover">
        <FileUp size={16} aria-hidden="true" /> Загрузить JSON
      </label>
      <input
        id="jsonf"
        type="file"
        accept="application/json"
        className="sr"
        data-act="jsonf"
        onChange={e => {
          const f = e.target.files?.[0];
          e.target.value = '';
          if (f) uploadDataset(f);
        }}
      />
      <Button data-act="paste" onClick={openPaste} title="Вставить диалог текстом и оценить его">
        <ClipboardPaste size={16} aria-hidden="true" /> Вставить диалог
      </Button>
    </>
  );
}

export function Queue() {
  const S = useS();
  const { params: p } = useRoute();
  const qa = S.role === 'qa';
  const cl = S.checklist,
    ap = S.appeals;
  const all: Row[] = S.dialogs.map((d: any) => ({ d, c: calc(d, cl, ap), g: groupOf(d, cl, ap) }));
  const cnt = (g: string) => all.filter(x => x.g === g).length;
  const totals = all.map(x => x.c.total).filter(x => x != null);
  const avg = totals.length ? r2(totals.reduce((a, b) => a + b, 0) / totals.length) : null;
  const two = twoModels(S);
  const seq = visibleRows(p);
  const filtered = hasFilters(p);
  const lost = (c: any) =>
    c.losses
      .slice(0, 3)
      .map((r: any) => `${r.c.id} ${ansTxt(r.c, r.a)}`)
      .join(', ');
  const toggle = (g: string) => go(setParam(p, 'grp', p.grp === g ? '' : g));
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

  return (
    <>
      <PageHead title="Диалоги" sub={qa ? 'Сначала разговоры с нарушениями и спорными ответами модели' : 'Ваши разговоры с оценкой по чек-листу: откройте строку, чтобы увидеть причины'}>
        {qa && <DatasetActions />}
      </PageHead>
      {qa && S.source && <p className="text-[13px] text-muted">{syncNote(S.source)}</p>}
      {qa && <RunPanel all={all} dialogs={filtered ? seq.map(x => x.d.id) : null} />}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5" aria-label="Быстрые фильтры">
        <Tile title="Грубые ошибки" n={cnt('risk')} note={`ещё ${S.dialogs.filter((d: any) => d.reviewed && flagsOf(d, cl, ap).length).length} проверено`} pressed={p.grp === 'risk'} onClick={() => toggle('risk')} g="risk" />
        <Tile
          title="Нужна проверка"
          n={cnt('review')}
          note={byJev(S.mode) ? 'Jev не уверен в ответе' : two ? 'модели разошлись или цитата не найдена' : 'цитата не найдена в реплике'}
          pressed={p.grp === 'review'}
          onClick={() => toggle('review')}
          g="review"
        />
        <Tile title="Без следующего шага" n={cnt('next')} note="следующий шаг не назван или неполный" pressed={p.grp === 'next'} onClick={() => toggle('next')} g="next" />
        <Tile title="Апелляции" n={ap.filter((a: any) => a.status === 'pending').length} note="ждут решения проверяющего" to={href('appeals')} />
        <Tile title="Средний итог" n={f2(avg)} note={`по ${totals.length} диалогам, открыть аналитику`} to={href('analytics')} />
      </section>

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
            <kbd className="pointer-events-none absolute right-2.5 rounded border border-line px-1 text-[11px] text-muted" title="Клавиша /: перейти к поиску">
              /
            </kbd>
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
            <Button
              size="sm"
              data-act="clear"
              onClick={() => {
                S.q = '';
                go(href('queue'));
                rerender();
              }}
            >
              <X size={16} aria-hidden="true" /> Сбросить фильтры
            </Button>
          )}
        </div>
        {!S.dialogs.length ? (
          <Empty
            action={
              qa && (
                <Button onClick={() => (document.querySelector('[data-act="load"]') as HTMLElement)?.click()}>
                  <Download size={16} aria-hidden="true" /> Получить набор
                </Button>
              )
            }
          >
            Набор не загружен{qa ? ': укажите group_id вверху и получите набор или вставьте диалог текстом.' : '.'}
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl min-w-[860px]">
              <thead>
                <tr>
                  <th>Диалог</th>
                  <th>Канал и язык</th>
                  <th className="num !text-right">Итог</th>
                  <th>Почему в очереди</th>
                  <th>Где потеряны баллы</th>
                  <th>Статус</th>
                </tr>
              </thead>
              {GROUPS.map(([g, title, tone, hint]) => {
                const rs = seq.filter(x => x.g === g);
                if (!rs.length) return null;
                return (
                  <tbody key={g}>
                    <tr className="grp">
                      <td colSpan={6}>
                        <Chip tone={tone} className="chip">
                          {title}: {rs.length}
                        </Chip>
                        <span className="ml-2 font-normal text-muted">{hint(two)}</span>
                      </td>
                    </tr>
                    {rs.map(x => {
                      const why = reasonOf(x.d, cl, ap);
                      return (
                        <tr
                          key={x.d.id}
                          className={cn('click', x.d.id === S.qsel && 'sel')}
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
                          </td>
                          <td>
                            {x.d.ch === 'call' ? 'Звонок' : 'Чат'}, {x.d.lang}
                          </td>
                          <td className="num font-bold">{f2(x.c.total)}</td>
                          <td>{why.text && <Chip tone={TONE[why.cls] ?? 'na'}>{why.text}</Chip>}</td>
                          <td className="text-[13px] text-muted">{lost(x.c) || '—'}</td>
                          <td>
                            <Status d={x.d} c={x.c} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                );
              })}
              {!seq.length && (
                <tbody>
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-muted">
                      По этим фильтрам диалогов нет. Сбросьте фильтры, чтобы увидеть весь набор.
                    </td>
                  </tr>
                </tbody>
              )}
            </table>
          </div>
        )}
      </section>
      <p className="text-xs text-muted">
        Клавиши <kbd className="rounded border border-line px-1">J</kbd> и <kbd className="rounded border border-line px-1">K</kbd> перемещаются по списку,{' '}
        <kbd className="rounded border border-line px-1">Enter</kbd> открывает карточку, <kbd className="rounded border border-line px-1">/</kbd> ставит курсор в поиск.
      </p>
    </>
  );
}
