// Карточка разговора: сводка (итог, потери, грубые ошибки), плеер и интонация звонка, расшифровка, критерии по секциям.
// Поведение — прежний web/js/views/card.js; контракт защиты — design.md, решение 4.
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import { ansTxt, f2, fn, mmss, titleOf } from '../lib/format.js';
import { groupOf, queueOrder } from '../lib/queue.js';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { ans, calc, flagsOf, flagWhy, lastDec } from '../lib/scoring.js';
import { api, reload, startRun, toast } from '../lib/state.js';
import { currentTheme, rerender, useS } from '../store';
import { TERMS, Term } from '../terms';
import { Button, Card, Chip, LinkButton, PageHead, Tip } from '../ui';
import { CountUp } from '../anim';
import { AppealDialog } from './AppealDialog';
import { ALL, Criteria, type Ctx } from './card/Criteria';
import { CardForms, type Pending } from './card/Forms';
import { IntonationPanel, useProsody } from './card/Intonation';
import { evalOf, OpsBar, rerun } from './card/Ops';
import { Player, seek } from './card/Player';
import { Transcript } from './card/Transcript';
import { lineBy, plural, scored } from './card/util';
import { Why } from './card/Why';

// функции, а не значения: t() срабатывает при отрисовке, на выбранном языке
const LANG: Record<string, () => string> = { RU: () => t('Русский'), KZ: () => t('Қазақша'), EN: () => t('English') };
const STATUS: Record<string, () => React.ReactNode> = {
  risk: () => <Chip tone="risk">{t('Грубая ошибка, нужна проверка')}</Chip>,
  review: () => <Chip tone="info">{t('Нужна проверка человека')}</Chip>,
  next: () => <Chip tone="ev">{t('Без следующего шага')}</Chip>,
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
  if (!d.cost) return t('Модель {model}. Диалог ещё не оценивался.', { model });
  const { calls, verifier_calls: v, usd, ms } = d.cost;
  return t('Оценка: {model}. {calls} {callsWord} основной модели и {v} {vWord} второго мнения, {sec} с, ${usd}.', {
    model,
    calls,
    callsWord: plural(calls, t('вызов'), t('вызова'), t('вызовов')),
    v,
    vWord: plural(v, t('запрос'), t('запроса'), t('запросов')),
    sec: fn(ms / 1000),
    usd: f2(usd),
  });
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
  const [again, setAgain] = useState(false);

  // Переход к реплике: прокрутка после отрисовки (критерий мог только что раскрыться).
  useEffect(() => {
    if (!flash) return;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById('L' + flash.n)?.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
  }, [flash]);

  if (!d)
    return (
      <PageHead
        title={t('Диалог не найден')}
        sub={
          <>
            {t('Диалога «{id}» нет в загруженном наборе.', { id })} <a href="#/queue">{t('Вернуться к списку')}</a>
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
  const group = groupOf(d, cl, S.appeals);
  const flagLoss = flags.length && fr ? { c: fr } : null;
  const fw = frr ? flagWhy(fr, frr) : null;

  const jump = (n: number) => setFlash(f => ({ n, k: (f?.k ?? 0) + 1 }));
  const seekLine = (l: any) => {
    if (l.s == null) return;
    seek(l.s);
    jump(l.n);
  };
  const goto = (cid: string, n?: number) => {
    setOpen(cid);
    const r = d.res[cid];
    const l = n != null ? lineBy(d, n) : r && r.ev && r.ev.length ? lineBy(d, r.ev[0]) : null;
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
      toast(t('Отметка не сохранена: {err}', { err: e.message }));
      return;
    } finally {
      setBusy(false);
    }
    await reload();
    toast(on ? t('{title} отмечен проверенным и уходит из верхних групп очереди.', { title: titleOf(d) }) : t('Отметка снята, диалог вернулся в очередь.'));
  };
  const evalNow = evalOf(S, d.id);
  const evalOne = () => {
    if (running) return;
    // запуск в replay заканчивается за миллисекунды: уведомление о старте рисуется сразу, до итогового
    flushSync(() => toast(t('Оценка {title} запущена.', { title: titleOf(d) })));
    startRun({ dialogs: [d.id], criteria: null });
  };

  const C = 2 * Math.PI * 52,
    dash = sum.total == null ? 0 : (C * sum.total) / 100;

  return (
    <>
      <nav className="flex flex-wrap items-center justify-between gap-2" aria-label={t('Навигация по очереди')}>
        <a href="#/queue" className="inline-flex items-center gap-1 text-[13px]">
          <ChevronLeft size={15} aria-hidden="true" /> {t('Все диалоги')}
        </a>
        <div className="flex items-center gap-2 text-[13px]">
          <span className="text-muted">
            {t('{n} из {total} в очереди', { n: i + 1, total: ord.length })}
          </span>
          {prev && (
            <LinkButton size="sm" href={href('d', prev)} aria-label={t('Предыдущий диалог')}>
              <ChevronLeft size={15} aria-hidden="true" /> {t('Предыдущий')}
            </LinkButton>
          )}
          {next && (
            <LinkButton size="sm" href={href('d', next)} aria-label={t('Следующий диалог')}>
              {t('Следующий')} <ChevronRight size={15} aria-hidden="true" />
            </LinkButton>
          )}
        </div>
      </nav>

      <PageHead title={titleOf(d)} sub={`${call ? t('Звонок, {dur}', { dur: mmss(d.dur || 0) }) : t('Чат')}, ${LANG[d.lang]?.() || d.lang}, ${d.at}, ${t('чек-лист v{v}', { v: cl.version })}`}>
        {(S.role !== 'operator' || group === 'risk') && STATUS[group]?.()}
        {d.reviewed && <Chip tone="ok">{t('Проверен')}</Chip>}
        {(evalNow === 'queued' || evalNow === 'running') && (
          <span className="text-[13px] text-muted" role="status" data-eval={evalNow}>
            {evalNow === 'queued' ? t('В очереди на оценку') : t('Оценивается…')}
          </span>
        )}
        {qa && todo > 0 && (
          <Tip content={running ? t('Идёт оценка набора. Кнопка станет активной, когда она закончится.') : null}>
            <span>
              <Button variant="primary" data-act="evalone" disabled={running} onClick={evalOne}>
                {running ? t('Идёт оценка…') : t('Оценить моделью')}
              </Button>
            </span>
          </Tip>
        )}
        {qa && todo < cl.criteria.length && (
          <Tip
            content={
              running
                ? t('Идёт оценка. Кнопка станет активной, когда она закончится.')
                : t('Модель оценит диалог ещё раз. Ручные ответы и решения по апелляциям не меняются, прежние оценки остаются в истории.')
            }
          >
            <span>
              <Button
                data-act="rerun"
                disabled={running || again}
                onClick={async () => {
                  setAgain(true);
                  await rerun(d);
                  setAgain(false);
                }}
              >
                {t('Оценить заново')}
              </Button>
            </span>
          </Tip>
        )}
        {qa && (
          <Button data-act="reviewed" disabled={busy} onClick={markReviewed}>
            {d.reviewed ? t('Снять отметку') : t('Отметить проверенным')}
          </Button>
        )}
        {S.role === 'operator' && (
          <Button variant="primary" data-act="appealtop" onClick={() => setAppealCid((sum.losses[0] || flagLoss)?.c?.id ?? scored(cl)[0]?.id)}>
            {t('Оспорить оценку')}
          </Button>
        )}
      </PageHead>
      <OpsBar d={d} onLine={jump} />

      <Card className="sum grid grid-cols-1 divide-y divide-line2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)] lg:divide-x lg:divide-y-0" aria-label={t('Сводка')}>
        <Panel>
          {/* «Итог» — прямой потомок блока с числом: шаг защиты no_total читает родителя этой надписи */}
          <Tip content={TERMS.total}>
            <h2 className="cursor-help self-start text-[15px] font-semibold">{t('Итог')}</h2>
          </Tip>
          <div className="flex flex-wrap items-center gap-4" data-total={sum.total ?? ""}>
            <svg width="124" height="124" viewBox="0 0 124 124" role="img" aria-label={t('Итог {total} из 100', { total: f2(sum.total) })} className="flex-none">
              <circle cx="62" cy="62" r="52" fill="none" className="stroke-accent-soft" strokeWidth="11" />
              <circle cx="62" cy="62" r="52" fill="none" className="stroke-accent" strokeWidth="11" strokeLinecap="round" strokeDasharray={`${dash} ${C}`} transform="rotate(-90 62 62)" />
              <text x="62" y="66" textAnchor="middle" fontSize="25" fontWeight="700" className="fill-ink">
                <CountUp value={sum.total} format={f2} />
              </text>
              <text x="62" y="86" textAnchor="middle" fontSize="12" className="fill-muted">
                {t('из 100')}
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
            <summary className="cursor-pointer font-semibold text-accent">{t('Как посчитан итог')}</summary>
            <p className="mt-1.5 text-muted">
              {t('{g} балла из {w} применимых, приведено к 100.', { g: fn(sum.G), w: sum.W })}
              {naRows.length ? (
                <>
                  {' '}
                  <Term k="na">N/A</Term> {t('у критериев {ids}: их вес распределён между остальными.', { ids: naRows.map((x: any) => x.id).join(', ') })}
                </>
              ) : (
                ' ' + t('N/A нет, веса не перераспределялись.')
              )}
              {sum.pending ? ' ' + t('Ждут оценки: {n}, итог предварительный.', { n: sum.pending }) : ''}
            </p>
          </details>
        </Panel>
        <Panel>
          <Label>{t('Почему снижена оценка')}</Label>
          {sum.losses.length ? (
            <div className="flex flex-col divide-y divide-line2">
              {sum.losses.slice(0, 3).map((r: any, k: number) => {
                const rr = d.res[r.c.id] || {},
                  ln = rr.ev && rr.ev.length ? lineBy(d, rr.ev[0]) : null;
                return (
                  <button
                    key={r.c.id}
                    type="button"
                    className="loss grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2.5 px-3 py-2 text-left hover:bg-hover"
                    data-act="goto"
                    data-cid={r.c.id}
                    onClick={() => goto(r.c.id)}
                  >
                    <span className="num pt-px text-[13px] font-semibold text-muted">{k + 1}.</span>
                    <span className="min-w-0 text-[13px]">
                      <b>{r.c.name}</b>, {t('ответ {a}', { a: ansTxt(r.c, r.a) })}
                      <br />
                      <span className="text-muted">{rr.why}</span>
                      {ln && (
                        <>
                          <br />
                          <span className="text-accent">
                            {t('Реплика {n}', { n: ln.n })}
                            {call ? `, ${mmss(ln.t)}` : ''}
                          </span>
                        </>
                      )}
                    </span>
                    <em className="num font-semibold not-italic text-ev">−{fn(r.loss)}</em>
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="text-muted">{t('Все применимые критерии выполнены полностью.')}</p>
          )}
          <p className="text-xs text-muted">
            {sum.losses.length > 3 ? t('Ещё {n} в списке критериев.', { n: sum.losses.length - 3 }) + ' ' : ''}
            {t('Сумма потерь равна 100 − итог.')}
          </p>
        </Panel>
        <Panel>
          <div className="flex items-center justify-between gap-2">
            <Label>
              <Term k="gross">{t('Грубые ошибки')}</Term>
            </Label>
            <span className="flex items-center gap-2">
              {frr?.basis != null && <Why title={t('Почему: грубые ошибки')} basis={frr.basis} d={d} onLine={jump} />}
              {flags.length ? <Chip tone="risk">{t('Найдены: {n}', { n: flags.length })}</Chip> : frr ? <Chip tone="ok">{t('Не найдены')}</Chip> : <Chip tone="ev">{t('Ждут оценки')}</Chip>}
            </span>
          </div>
          {fw &&
            fw.qs
              .filter((x: any) => fa && fa[x.q.k])
              .map((x: any) => {
                const n = (x.ev.length ? x.ev : frr.ev || [])[0];
                const ln = n != null ? lineBy(d, n) : null;
                return (
                  <div key={x.q.k} className="flex flex-col gap-1 text-[13px]">
                    <span>
                      <Chip tone="risk">{x.q.label}</Chip>
                    </span>
                    {x.why && <p>{x.why}</p>}
                    {ln && <p className="border-l-2 border-ev pl-3 text-ink2">«{ln.text}»</p>}
                    {ln && (
                      <span>
                        <Button size="sm" data-act="goto" data-cid={fr.id} onClick={() => goto(fr.id, ln.n)}>
                          {t('К реплике {n}', { n: ln.n })}
                        </Button>
                      </span>
                    )}
                  </div>
                );
              })}
          {fr && (
            <p className="text-[13px] text-muted">
              {flags.length ? t('Не найдено:') : t('Проверено:')}{' '}
              {(fr.questions || [])
                .filter((q: any) => !(fa && fa[q.k]))
                .map((q: any) => q.label)
                .join(', ')}
              .
            </p>
          )}
          <p className="text-xs text-muted">
            {S.mode?.verifier || answered
              ? t('Каждый вид проверяется отдельным вопросом. Грубая ошибка ставится, если её нашла хотя бы одна из двух моделей. Итог она не обнуляет.')
              : t('Каждый вид проверяется отдельным вопросом. Грубая ошибка ставится, если её нашла модель. Итог она не обнуляет.')}
          </p>
          {answered > 0 && S.role !== 'operator' && (
            <p className="mt-auto border-t border-line2 pt-2.5 text-[13px]">
              <Term k="second">{t('Второе мнение')}</Term> {t('совпало по {n} из {total} критериев', { n: answered - disagree(S, d).length, total: answered })}
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
        <section className="min-w-0 rounded-card border border-line bg-surface shadow-card" aria-label={t('Расшифровка')}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <h2 className="text-base font-semibold">{call ? t('Расшифровка звонка') : t('Переписка')}</h2>
            <span className="text-xs text-muted">{call ? t('Время от начала записи. ▶ ставит запись на начало реплики') : t('Время из чата, исходные метки сохранены')}</span>
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
        <section className="min-w-0 overflow-hidden rounded-card border border-line bg-surface shadow-card" aria-label={t('Оценка по критериям')}>
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <h2 className="text-base font-semibold">{t('Оценка по критериям')}</h2>
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted">{t('Нажмите на критерий: обоснование и реплики-основания')}</span>
              <Button size="sm" data-act="critall" aria-expanded={open === ALL} onClick={() => setOpen(open === ALL ? null : ALL)}>
                {open === ALL ? t('Свернуть') : t('Развернуть все обоснования')}
              </Button>
            </span>
          </div>
          <Criteria ctx={ctx} sum={sum} />
        </section>
      </div>
      {qa && <p className="meta text-xs text-muted">{costLine(S, d)}</p>}

      <CardForms d={d} p={form} onClose={() => setForm(null)} />
      <AppealDialog dialog={d} cid={appealCid} onClose={() => setAppealCid(null)} />
    </>
  );
}
