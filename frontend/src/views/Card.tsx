// Карточка разговора: сводка (итог, потери, грубые ошибки), плеер и интонация звонка, расшифровка, критерии по секциям.
// Поведение — прежний web/js/views/card.js; контракт защиты — design.md, решение 4.
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import { ansTxt, f2, fn, mmss, titleOf } from '../lib/format.js';
import { groupOf, queueOrder } from '../lib/queue.js';
import { href } from '../lib/router.js';
import { ans, calc, flagsOf, lastDec } from '../lib/scoring.js';
import { api, reload, startRun, toast } from '../lib/state.js';
import { currentTheme, rerender, useS } from '../store';
import { Button, Card, Chip, LinkButton, PageHead } from '../ui';
import { AppealDialog } from './AppealDialog';
import { ALL, Criteria, type Ctx } from './card/Criteria';
import { CardForms, type Pending } from './card/Forms';
import { IntonationPanel, useProsody } from './card/Intonation';
import { Player, seek } from './card/Player';
import { Transcript } from './card/Transcript';
import { lineBy, plural, scored } from './card/util';

const LANG: Record<string, string> = { RU: 'Русский', KZ: 'Қазақша', EN: 'English' };
const STATUS: Record<string, React.ReactNode> = {
  risk: <Chip tone="risk">Грубая ошибка, нужна проверка</Chip>,
  review: <Chip tone="info">Нужна проверка человека</Chip>,
  next: <Chip tone="ev">Без следующего шага</Chip>,
};

function disagree(S: any, d: any) {
  return scored(S.checklist).filter((c: any) => {
    const r = d.res[c.id];
    return r && r.alt != null && r.alt !== r.a && !lastDec(d, c.id, S.appeals);
  });
}

function defaultOpen(S: any, d: any, sum: any) {
  const dc = disagree(S, d)[0];
  if (dc) return dc.id;
  if (sum.losses[0]) return sum.losses[0].c.id;
  const fc = S.checklist.criteria.find((c: any) => c.type === 'flag');
  return flagsOf(d, S.checklist, S.appeals).length && fc ? fc.id : scored(S.checklist)[0]?.id;
}

// Стоимость последней оценки — Dialog.cost как есть, по критериям не пересчитывается.
function costLine(S: any, d: any) {
  const model = S.mode ? S.mode.model : '';
  if (!d.cost) return `Модель ${model}. Диалог ещё не оценивался.`;
  const { calls, verifier_calls: v, usd, ms } = d.cost;
  return `Оценка: ${model}. ${calls} ${plural(calls, 'вызов', 'вызова', 'вызовов')} основной модели и ${v} ${plural(v, 'запрос', 'запроса', 'запросов')} второго мнения, ${fn(ms / 1000)} с, $${f2(usd)}.`;
}

const Label = ({ children }: { children: React.ReactNode }) => <h2 className="text-[15px] font-semibold">{children}</h2>;
const Panel = ({ children }: { children: React.ReactNode }) => <div className="flex min-w-0 flex-col gap-2.5 p-4">{children}</div>;

export function CardView({ id }: { id: string | null }) {
  const S = useS();
  const d = S.dialogs.find((x: any) => x.id === id);
  const prosody = useProsody(d);
  const [flash, setFlash] = useState<{ n: number; k: number } | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [form, setForm] = useState<Pending>(null);
  const [appealCid, setAppealCid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Переход к реплике: прокрутка после отрисовки (критерий мог только что раскрыться).
  useEffect(() => {
    if (!flash) return;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById('L' + flash.n)?.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
  }, [flash]);

  if (!d)
    return (
      <PageHead
        title="Диалог не найден"
        sub={
          <>
            Диалога «{id}» нет в загруженном наборе. <a href="#/queue">Вернуться к списку</a>
          </>
        }
      />
    );

  const cl = S.checklist,
    call = d.ch === 'call';
  const sum = calc(d, cl, S.appeals);
  if (!(d.id in S.open)) S.open[d.id] = defaultOpen(S, d, sum);
  const open: string | null = S.open[d.id];
  const setOpen = (v: string | null) => {
    S.open[d.id] = v;
    rerender();
  };
  const ord = queueOrder(S.dialogs, cl, S.appeals),
    i = ord.indexOf(d.id);
  const prev = ord[i - 1],
    next = ord[i + 1];
  const naRows = scored(cl).filter((c: any) => ans(d, c.id, S.appeals) === 'na');
  const flags = flagsOf(d, cl, S.appeals);
  const withRes = scored(cl).filter((c: any) => d.res[c.id]);
  const answered = withRes.some((c: any) => d.res[c.id].alt != null) ? withRes.length : 0;
  const fr = cl.criteria.find((c: any) => c.type === 'flag'),
    frr = fr && d.res[fr.id],
    fa = frr && ans(d, fr.id, S.appeals);
  const todo = cl.criteria.filter((c: any) => !d.res[c.id]).length;
  const running = Boolean(S.run && S.run.status === 'running');
  const qa = S.role === 'qa';

  const jump = (n: number) => setFlash(f => ({ n, k: (f?.k ?? 0) + 1 }));
  const seekLine = (l: any) => {
    if (l.s == null) return;
    seek(l.s);
    jump(l.n);
  };
  const goto = (cid: string) => {
    setOpen(cid);
    const r = d.res[cid];
    const l = r && r.ev && r.ev.length ? lineBy(d, r.ev[0]) : null;
    if (!l) return;
    jump(l.n);
    if (l.s != null) seek(l.s, false);
  };
  const ctx: Ctx = {
    d,
    open,
    toggle: cid => setOpen(open === cid ? null : cid),
    jump,
    seekLine,
    manual: c => setForm({ kind: 'manual', c }),
    review: (c, val) => setForm({ kind: 'review', c, val }),
    appeal: setAppealCid,
    hover: setHover,
  };
  const sel = new Set<number>((d.res[open as string] && d.res[open as string].ev) || []);
  const hoverEv = hover && d.res[hover] ? d.res[hover].ev || [] : [];

  const markReviewed = async () => {
    const on = !d.reviewed;
    setBusy(true);
    try {
      await api.postReviewed(d.id, on);
    } catch (e: any) {
      toast(`Отметка не сохранена: ${e.message}`);
      return;
    } finally {
      setBusy(false);
    }
    await reload();
    toast(on ? `${titleOf(d)} отмечен проверенным и уходит из верхних групп очереди.` : 'Отметка снята, диалог вернулся в очередь.');
  };
  const evalOne = () => {
    if (running) return;
    // запуск в replay заканчивается за миллисекунды: уведомление о старте рисуется сразу, до итогового
    flushSync(() => toast(`Оценка ${titleOf(d)} запущена.`));
    startRun({ dialogs: [d.id], criteria: null });
  };

  const C = 2 * Math.PI * 52,
    dash = sum.total == null ? 0 : (C * sum.total) / 100;

  return (
    <>
      <nav className="flex flex-wrap items-center justify-between gap-2" aria-label="Навигация по очереди">
        <a href="#/queue" className="inline-flex items-center gap-1 text-[13px]">
          <ChevronLeft size={15} aria-hidden="true" /> Все диалоги
        </a>
        <div className="flex items-center gap-2 text-[13px]">
          <span className="text-muted">
            {i + 1} из {ord.length} в очереди
          </span>
          {prev && (
            <LinkButton size="sm" href={href('d', prev)} aria-label="Предыдущий диалог" title="Предыдущий диалог">
              <ChevronLeft size={15} aria-hidden="true" /> Предыдущий
            </LinkButton>
          )}
          {next && (
            <LinkButton size="sm" href={href('d', next)} aria-label="Следующий диалог" title="Следующий диалог">
              Следующий <ChevronRight size={15} aria-hidden="true" />
            </LinkButton>
          )}
        </div>
      </nav>

      <PageHead title={titleOf(d)} sub={`${call ? `Звонок, ${mmss(d.dur || 0)}` : 'Чат'}, ${LANG[d.lang] || d.lang}, ${d.at}, чек-лист v${cl.version}`}>
        {STATUS[groupOf(d, cl, S.appeals)]}
        {d.reviewed && <Chip tone="ok">Проверен</Chip>}
        {qa && todo > 0 && (
          <Button variant="primary" data-act="evalone" disabled={running} onClick={evalOne} title={`Ждут оценки: ${todo}. Ответы, поставленные вручную, модель не меняет`}>
            {running ? 'Идёт оценка…' : 'Оценить моделью'}
          </Button>
        )}
        {qa && (
          <Button data-act="reviewed" disabled={busy} onClick={markReviewed} title="Проверенный диалог уходит из верхних групп очереди">
            {d.reviewed ? 'Снять отметку' : 'Отметить проверенным'}
          </Button>
        )}
      </PageHead>

      <Card className="sum grid grid-cols-1 divide-y divide-line2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)] lg:divide-x lg:divide-y-0" aria-label="Сводка">
        <Panel>
          <h2 className="text-[15px] font-semibold">Итог</h2>
          <div className="ring flex flex-wrap items-center gap-4">
            <svg width="124" height="124" viewBox="0 0 124 124" role="img" aria-label={`Итог ${f2(sum.total)} из 100`} className="flex-none">
              <circle cx="62" cy="62" r="52" fill="none" className="stroke-accent-soft" strokeWidth="11" />
              <circle cx="62" cy="62" r="52" fill="none" className="stroke-accent" strokeWidth="11" strokeLinecap="round" strokeDasharray={`${dash} ${C}`} transform="rotate(-90 62 62)" />
              <text x="62" y="66" textAnchor="middle" fontSize="25" fontWeight="700" className="fill-ink">
                {f2(sum.total)}
              </text>
              <text x="62" y="86" textAnchor="middle" fontSize="12" className="fill-muted">
                из 100
              </text>
            </svg>
            <div className="secs flex min-w-[150px] flex-1 flex-col gap-1 text-[13px]">
              {sum.secs.map((s: any) => (
                <div key={s.name} className="flex justify-between gap-2">
                  <span className="text-ink2">{s.name}</span>
                  <b className="num">
                    {fn(s.g)} / {s.w}
                  </b>
                </div>
              ))}
            </div>
          </div>
          <details className="text-[13px]">
            <summary className="cursor-pointer font-semibold text-accent">Как посчитан итог</summary>
            <p className="mt-1.5 text-muted">
              {fn(sum.G)} балла из {sum.W} применимых, приведено к 100.
              {naRows.length ? ` N/A у критериев ${naRows.map((x: any) => x.id).join(', ')}: их вес распределён между остальными.` : ' N/A нет, веса не перераспределялись.'}
              {sum.pending ? ` Ждут оценки: ${sum.pending}, итог предварительный.` : ''}
            </p>
          </details>
        </Panel>
        <Panel>
          <Label>Почему снижена оценка</Label>
          {sum.losses.length ? (
            sum.losses.slice(0, 3).map((r: any, k: number) => {
              const rr = d.res[r.c.id] || {},
                ln = rr.ev && rr.ev.length ? lineBy(d, rr.ev[0]) : null;
              return (
                <button
                  key={r.c.id}
                  type="button"
                  className="loss grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-lg border border-line px-3 py-2 text-left hover:bg-hover"
                  data-act="goto"
                  data-cid={r.c.id}
                  onClick={() => goto(r.c.id)}
                  title="Открыть критерий и реплику-основание"
                >
                  <span className="num pt-px text-[13px] font-semibold text-muted">{k + 1}.</span>
                  <span className="min-w-0 text-[13px]">
                    <b>{r.c.name}</b>, {ansTxt(r.c, r.a)}
                    <br />
                    <span className="text-muted">{rr.why}</span>
                    {ln && (
                      <>
                        <br />
                        <span className="text-accent">
                          Реплика {ln.n}
                          {call ? `, ${mmss(ln.t)}` : ''}
                        </span>
                      </>
                    )}
                  </span>
                  <em className="num font-semibold not-italic text-ev">−{fn(r.loss)}</em>
                </button>
              );
            })
          ) : (
            <p className="text-muted">Все применимые критерии выполнены полностью.</p>
          )}
          <p className="text-xs text-muted">
            {sum.losses.length > 3 ? `Ещё ${sum.losses.length - 3} в списке критериев. ` : ''}Потери посчитаны после перераспределения N/A и в сумме дают 100 − итог.
          </p>
        </Panel>
        <Panel>
          <div className="flex items-center justify-between gap-2">
            <Label>Грубые ошибки</Label>
            {flags.length ? <Chip tone="risk">Найдены: {flags.length}</Chip> : frr ? <Chip tone="ok">Не найдены</Chip> : <Chip tone="ev">Ждут оценки</Chip>}
          </div>
          {fr &&
            (fr.questions || []).map((q: any) => (
              <div key={q.k} className="flex justify-between gap-2 text-[13px]">
                <span>{q.label}</span>
                {fa && fa[q.k] ? <b className="text-risk">да</b> : <span className="text-muted">нет</span>}
              </div>
            ))}
          {flags.length > 0 && frr.ev && frr.ev.length > 0 && (
            <div>
              <Button size="sm" data-act="goto" data-cid={fr.id} onClick={() => goto(fr.id)}>
                Показать реплику {frr.ev.join(', ')}
              </Button>
            </div>
          )}
          <p className="text-xs text-muted">
            Каждый вид проверяется отдельным вопросом. Флаг ставится, если нарушение нашла {S.mode?.verifier || answered ? 'хотя бы одна из двух моделей' : 'модель'}. Итог он не обнуляет.
          </p>
          {answered > 0 && (
            <p className="mt-auto border-t border-line2 pt-2.5 text-[13px]" title="Второе мнение: ответ второй модели по тем же критериям">
              Второе мнение совпало по {answered - disagree(S, d).length} из {answered} критериев
            </p>
          )}
        </Panel>
      </Card>

      {call && d.lines && (
        <>
          <Player key={d.id} d={d} losses={sum.losses} theme={currentTheme()} onNow={setNow} onPin={goto} />
          <IntonationPanel p={prosody} />
        </>
      )}

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <section className="min-w-0 rounded-card border border-line bg-surface shadow-card" aria-label="Расшифровка">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <h2 className="text-base font-semibold">{call ? 'Расшифровка звонка' : 'Переписка'}</h2>
            <span className="text-xs text-muted">{call ? 'Время от начала записи. ▶ ставит запись на начало реплики' : 'Время из чата, исходные метки сохранены'}</span>
          </div>
          <div className="tr flex max-h-[78vh] flex-col gap-2 overflow-y-auto p-3" id="tr">
            <Transcript
              d={d}
              prosody={prosody}
              marks={{ sel, hl: new Set(hoverEv), now, flash: flash?.n ?? null, onFlashEnd: () => setFlash(null) }}
              onCrit={ctx.toggle}
              onSeek={seekLine}
            />
          </div>
        </section>
        <section className="min-w-0 overflow-hidden rounded-card border border-line bg-surface shadow-card" aria-label="Оценка по критериям">
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <h2 className="text-base font-semibold">Оценка по критериям</h2>
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted">Наведите на критерий, чтобы подсветить реплики</span>
              <Button size="sm" data-act="critall" aria-expanded={open === ALL} onClick={() => setOpen(open === ALL ? null : ALL)}>
                {open === ALL ? 'Свернуть' : 'Развернуть все обоснования'}
              </Button>
            </span>
          </div>
          <Criteria ctx={ctx} sum={sum} />
        </section>
      </div>
      <p className="meta text-xs text-muted">{costLine(S, d)}</p>

      <CardForms d={d} p={form} onClose={() => setForm(null)} />
      <AppealDialog dialog={d} cid={appealCid} onClose={() => setAppealCid(null)} />
    </>
  );
}
