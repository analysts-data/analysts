// Оценка по критериям: секции, блок критерия [data-cid] с переключателем aria-expanded, балл «7,5 / 15»,
// обоснование, основания с переходом к реплике, второе мнение, N/A, история решений, ручной ответ и апелляция.
import { ChevronDown } from 'lucide-react';
import { ansTxt, f2, fn, mmss } from '../../lib/format.js';
import { byJev } from '../../lib/queue.js';
import { ans, calc, flagWhy, frac, lastDec } from '../../lib/scoring.js';
import { t } from '../../lib/i18n.js';
import { href } from '../../lib/router.js';
import { S } from '../../store';
import { Term } from '../../terms';
import { Button, Chip, cn, Tip, type Tone } from '../../ui';
import { History } from './History';
import { RecheckMenu } from './Recheck';
import { evalOf } from './Ops';
import { OrgPlayer } from './Transcript';
import { lineBy, MANUAL, ptsTxt, tone } from './util';
import { Why } from './Why';

export const ALL = '*'; // S.open[dialog]: раскрыты все критерии
const WHO: Record<string, () => string> = { client: () => t('клиент'), operator: () => t('оператор'), bot: () => t('бот'), system: () => t('система') };

export type Ctx = {
  d: any;
  open: string | null;
  toggle: (cid: string) => void;
  jump: (n: number) => void;
  seekLine: (l: any) => void;
  manual: (c: any) => void;
  review: (c: any, val: any) => void;
  appeal: (cid: string) => void;
  hover: (cid: string | null) => void;
};

const Label = ({ children }: { children: React.ReactNode }) => <span className="text-[13px] font-semibold text-ink2">{children}</span>;
const qa = () => S.role === 'qa';
const firstSentence = (s: string) => (s || '').split(/(?<=[.!?])\s/)[0];
const pendingOf = (d: any, cid: string) => S.appeals.find((x: any) => x.dlg === d.id && x.cid === cid && x.status === 'pending');

// Пояснение в теле критерия: строка с левой линией цвета по смыслу, без плашки. data-note — метка для тестов.
const LINE: Record<string, string> = { check: 'border-ev', second: 'border-info', na: 'border-na', better: 'border-accent' };
const Note = ({ kind, children }: { kind: string; children: React.ReactNode }) => (
  <div data-note={kind} className={cn('flex flex-col gap-2 border-l-2 pl-3 text-[13px]', LINE[kind])}>
    {children}
  </div>
);
const AnsChip = ({ c, a, tone: t }: { c: any; a: any; tone: Tone }) => <Chip tone={t}>{ansTxt(c, a)}</Chip>;

export function Criteria({ ctx, sum }: { ctx: Ctx; sum: any }) {
  const cl = S.checklist;
  return (
    <>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_5rem_18px] gap-2 border-t border-line py-1.5 pl-4 pr-2 text-xs text-muted" aria-hidden="true">
        <span />
        <span className="text-right">{t('Ответ модели')}</span>
        <span className="text-right">{t('Баллы / вес')}</span>
        <span />
      </div>
      {cl.sections.map((s: string, si: number) => {
        const cs = cl.criteria.filter((x: any) => x.sec === si);
        if (!cs.length) return null;
        const sc = sum.secs.find((x: any) => x.name === s);
        return (
          <div key={si}>
            <div className="sechead flex justify-between border-y border-line bg-sunken px-4 py-1.5 text-xs font-semibold text-muted">
              <span>{s}</span>
              <span className="num">{sc ? `${fn(sc.g)} / ${sc.w}` : ''}</span>
            </div>
            {cs.map((c: any) => (
              <Crit key={c.id} c={c} ctx={ctx} />
            ))}
          </div>
        );
      })}
    </>
  );
}

function Crit({ c, ctx }: { c: any; ctx: Ctx }) {
  const { d, open } = ctx;
  const r = d.res[c.id];
  const a = ans(d, c.id, S.appeals);
  const isOpen = open === c.id || open === ALL;
  const busy = !r && evalOf(S, d.id) === 'running';
  let chip, pts, lowered, gist;
  if (c.type === 'flag') {
    const found = r && a ? (c.questions || []).filter((q: any) => a[q.k]) : [];
    lowered = found.length > 0;
    chip = !r ? (
      <Chip tone="ev">{busy ? t('оценивается…') : t('ждёт оценки')}</Chip>
    ) : lowered ? (
      <Chip tone="risk" className="max-w-[40vw]">
        <span className="truncate">{found.length === 1 ? t('Найдена: {kind}', { kind: found[0].label }) : t('Найдены: {n}', { n: found.length })}</span>
      </Chip>
    ) : (
      <Chip tone="ok">{t('Не найдены')}</Chip>
    );
    pts = t('без баллов');
    gist = found.length > 1 ? ansTxt(c, a) : '';
  } else {
    const f = frac(c, a);
    lowered = Boolean(r && f != null && f < 1);
    chip = busy ? <Chip tone="ev">{t('оценивается…')}</Chip> : <AnsChip c={c} a={a} tone={tone(c, a)} />;
    pts = ptsTxt(c, a);
    gist = r ? firstSentence(r.why) : '';
  }
  const pa = pendingOf(d, c.id);
  return (
    <article
      className={cn('crit border-b border-line2', isOpen && 'open bg-sunken')}
      data-cid={c.id}
      data-ev={(r?.ev || []).join(',')}
      onMouseEnter={() => ctx.hover(c.id)}
      onMouseLeave={() => ctx.hover(null)}
      onFocus={() => ctx.hover(c.id)}
    >
      <div className="flex items-center hover:bg-hover">
        <button
          type="button"
          className="crit-row grid min-w-0 flex-1 grid-cols-[2.2rem_minmax(0,1fr)_auto_5rem_18px] items-center gap-2 py-2.5 pl-4 pr-2 text-left"
          data-act="crit"
          data-cid={c.id}
          aria-expanded={isOpen}
          onClick={() => ctx.toggle(c.id)}
        >
          <span className="text-[13px] text-muted">{c.id}</span>
          <span className="min-w-0">
            <span className="block">{c.name}</span>
            {!isOpen && gist && <span className="block truncate text-xs text-muted">{gist}</span>}
          </span>
          {chip}
          <span className="num text-right text-[13px] font-semibold">{pts}</span>
          <ChevronDown size={16} className={cn('text-muted transition-transform', isOpen && 'rotate-180')} aria-hidden="true" />
        </button>
        {S.role === 'operator' &&
          (pa ? (
            <Chip tone="info" className="mr-3">
              {t('Апелляция на рассмотрении')}
            </Chip>
          ) : (
            lowered &&
            !isOpen && (
              <Button variant="ghost" size="sm" className="mr-2" data-act="appealrow" data-cid={c.id} onClick={() => ctx.appeal(c.id)}>
                {t('Оспорить')}
              </Button>
            )
          ))}
      </div>
      {isOpen && (
        <div className="crit-body flex flex-col gap-3 px-4 pb-4 pt-1 text-sm">
          <Body c={c} r={r} a={a} ctx={ctx} />
        </div>
      )}
    </article>
  );
}

function Body({ c, r, a, ctx }: { c: any; r: any; a: any; ctx: Ctx }) {
  const { d } = ctx;
  if (!r || a == null)
    return (
      <Note kind="check">
        <span>{t('Критерий ждёт оценки. Пока итог считается без него.')}</span>
        {qa() && (
          <span>
            <Button size="sm" data-act="manual" data-cid={c.id} onClick={() => ctx.manual(c)}>
              {t('Оценить вручную')}
            </Button>
          </span>
        )}
      </Note>
    );
  const hist = S.appeals.filter((x: any) => x.dlg === d.id && x.cid === c.id && (x.status === 'confirmed' || x.status === 'changed'));
  const pa = pendingOf(d, c.id);
  const blocked = S.appeals.some((x: any) => x.dlg === d.id && x.cid === c.id && x.status !== 'closed');
  return (
    <>
      {c.type === 'flag' ? <FlagBody c={c} r={r} a={a} ctx={ctx} /> : <ScoredBody c={c} r={r} a={a} ctx={ctx} />}
      {hist.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label>{t('История оценки')}</Label>
          <div className="hist grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 text-[13px]">
            <span className="text-muted">{t('Исходная')}</span>
            <span>{t('Модель, {at}', { at: d.at })}</span>
            <Chip tone="na">{ansTxt(c, r.a)}</Chip>
            {hist.map((h: any) => (
              <Hist key={h.id} c={c} h={h} />
            ))}
            {c.type !== 'flag' && (
              <>
                <span className="text-muted">{t('Итог')}</span>
                <span>
                  {t('Пересчитан по формуле чек-листа, было')}{' '}
                  <span className="num">{f2(calc(d, S.checklist, S.appeals.filter((x: any) => !(x.dlg === d.id && x.cid === c.id))).total)}</span>
                </span>
                <b className="num">{f2(calc(d, S.checklist, S.appeals).total)}</b>
              </>
            )}
          </div>
        </div>
      )}
      {(r.model === MANUAL || (!blocked && qa())) && (
        <div className="flex flex-wrap items-center gap-2">
          {r.model === MANUAL && (
            <Chip tone="info">
              <Term k="manual">{t('Исправлено специалистом')}</Term>
            </Chip>
          )}
          {!blocked && qa() && (
            <Button size="sm" data-act="manual" data-cid={c.id} onClick={() => ctx.manual(c)}>
              {t('Исправить оценку')}
            </Button>
          )}
          {!blocked && qa() && <RecheckMenu dialogs={[d.id]} criteria={[c.id]} size="sm" />}
        </div>
      )}
      {S.role !== 'operator' && <History d={d} c={c} lock={pa ? t('По критерию есть апелляция на рассмотрении: прежнюю оценку можно сделать текущей после решения.') : null} />}
      {pa ? (
        <p className="flex items-center gap-2">
          <Chip tone="info">{t('Апелляция на рассмотрении')}</Chip>
          <a href={href('appeals', pa.id)} className="text-[13px]">
            {t('Открыть апелляцию')}
          </a>
        </p>
      ) : (
        S.role !== 'reviewer' && (
          <div>
            <Button variant={qa() ? 'ghost' : 'default'} size={qa() ? 'sm' : 'md'} data-act="appeal" data-cid={c.id} onClick={() => ctx.appeal(c.id)}>
              {t('Оспорить оценку')}
            </Button>
          </div>
        )
      )}
    </>
  );
}

const Hist = ({ c, h }: { c: any; h: any }) => (
  <>
    <span className="text-muted">{h.kind === 'appeal' ? t('Апелляция') : t('Решение')}</span>
    <span>
      {h.reviewer}, {h.decidedAt}: «{h.reason}»
    </span>
    <Chip tone={h.status === 'changed' ? 'info' : 'ok'}>{h.status === 'changed' ? ansTxt(c, h.to) : t('подтверждено')}</Chip>
  </>
);

function Evidence({ ev, ctx }: { ev: number[]; ctx: Ctx }) {
  const { d } = ctx;
  const call = d.ch === 'call';
  return (
    <>
      {(ev || []).map(n => {
        const l = lineBy(d, n);
        if (!l) return null;
        return (
          <div key={n} className="quote flex flex-wrap items-start justify-between gap-2 border-l-2 border-ev py-0.5 pl-3">
            <div className="min-w-0 flex-1">
              <span className="text-xs text-muted">
                {n}, {WHO[l.who]?.() || l.who}
              </span>
              <br />«{l.text}»
            </div>
            <span className="flex gap-1.5">
              <Button size="sm" data-act="ev" data-n={n} onClick={() => ctx.jump(n)}>
                {t('К реплике')}
              </Button>
              {call &&
                (l.s == null ? (
                  <OrgPlayer d={d} />
                ) : (
                  <Tip content={t('Слушать запись с {at}', { at: mmss(l.s) })}>
                    <Button size="sm" data-act="seek" data-n={l.n} onClick={() => ctx.seekLine(l)} aria-label={t('Перейти к фрагменту, {at}', { at: mmss(l.s) })}>
                      ▶ {mmss(l.s)}
                    </Button>
                  </Tip>
                ))}
            </span>
          </div>
        );
      })}
    </>
  );
}

// Флаг: по каждому вопросу ответ с учётом решения, причина модели и реплики-основания этого нарушения.
function FlagBody({ c, r, a, ctx }: { c: any; r: any; a: any; ctx: Ctx }) {
  const fw = flagWhy(c, r);
  return (
    <>
      <div className="flex flex-col gap-2">
        {fw.qs.map((x: any) => (
          <div key={x.q.k} className="flex flex-col gap-1.5 border-t border-line2 pt-2" data-k={x.q.k}>
            <div className="flex items-center justify-between gap-2">
              <b>{x.q.label}</b>
              {a[x.q.k] ? <Chip tone="risk">{t('найдено')}</Chip> : <span className="text-[13px] text-muted">{t('не найдено')}</span>}
            </div>
            {x.why && <p className="text-[13px]">{x.why}</p>}
            <Evidence ev={x.ev} ctx={ctx} />
          </div>
        ))}
      </div>
      {fw.rest && <p>{fw.rest}</p>}
      {r.basis != null && (
        <span>
          <Why title={t('Почему: {name}', { name: c.name })} basis={r.basis} d={ctx.d} onLine={ctx.jump} />
        </span>
      )}
      {fw.ev.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label>{t('Основание')}</Label>
          <Evidence ev={fw.ev} ctx={ctx} />
        </div>
      )}
    </>
  );
}

function ScoredBody({ c, r, a, ctx }: { c: any; r: any; a: any; ctx: Ctx }) {
  const { d } = ctx;
  const hasEv = (r.ev || []).some((n: number) => lineBy(d, n));
  const f = frac(c, a);
  const altDiff = r.alt != null && r.alt !== a;
  const dec = lastDec(d, c.id, S.appeals);
  const op = S.role === 'operator';
  return (
    <>
      <div className="flex flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2 text-[13px]">
          <span>
            {f == null
              ? `${t('Ответ:')} ${ansTxt(c, a)}`
              : c.type === 'scale'
                ? t('Ответ: {a} по шкале, это {p} из {w} баллов', { a: ansTxt(c, a), p: fn(c.w * f), w: c.w })
                : t('Ответ: {a}, это {p} из {w} баллов', { a: ansTxt(c, a), p: fn(c.w * f), w: c.w })}
          </span>
          {altDiff && !op && (
            <span className="text-muted">{t('Второе мнение: {a}', { a: ansTxt(c, r.alt) })}</span>
          )}
        </p>
        {c.type === 'scale' && c.stepText && c.stepText[a] && (
          <span className="text-xs text-muted">
            {a}: {c.stepText[a]}
          </span>
        )}
      </div>
      {a === 'na' ? (
        <Note kind="na">
          <p>
            <b>{t('N/A: не применимо.')}</b> {t('Условие N/A выполнено:')} {c.naCond} {r.why} {t('Вес {w} распределён между применимыми критериями.', { w: c.w })}
          </p>
        </Note>
      ) : (
        <div>
          <Label>{t('Обоснование')}</Label>
          <p>{r.why}</p>
        </div>
      )}
      {/* пропущенное действие: реплик-оснований нет, модель называет проверенный участок; Jev участок не называет */}
      {!byJev(r) && ((a === 'no' && (r.seg || !hasEv)) || (c.type === 'scale' && f != null && f < 1 && !hasEv)) && (
        <p className="text-[13px]">
          {t('Проверен участок:')} <b>{r.seg || t('весь диалог')}</b>. {a === 'no' ? t('Ожидаемого действия там нет.') : t('Полностью действие там не выполнено.')}
        </p>
      )}
      {hasEv && (
        <div className="flex flex-col gap-1.5">
          <Label>{t('Основание')}</Label>
          <Evidence ev={r.ev} ctx={ctx} />
        </div>
      )}
      {r.evFail && !dec && !op && (
        <Note kind="check">
          <span>
            {byJev(r) ? (
              <>
                <b>{t('Jev не уверен в ответе')}</b>: {t('вероятность ниже порога.')}
              </>
            ) : (
              <>
                <b>{t('Цитата не нашлась в указанной реплике')}</b> {t('и после повтора.')}
              </>
            )}{' '}
            {t('Ответ')} <Chip tone="ev">{t('на проверку')}</Chip>
          </span>
          {qa() && (
            <span className="flex flex-wrap gap-2">
              <Button size="sm" data-act="review" data-cid={c.id} data-val={String(a)} onClick={() => ctx.review(c, a)}>
                {t('Оставить {a}', { a: ansTxt(c, a) })}
              </Button>
              <Button size="sm" data-act="review" data-cid={c.id} onClick={() => ctx.review(c, null)}>
                {t('Изменить')}
              </Button>
            </span>
          )}
        </Note>
      )}
      {op ? null : r.alt != null && r.alt !== r.a && !dec ? (
        <Note kind="second">
          <span>
            <b>{t('Второе мнение: {a}.', { a: ansTxt(c, r.alt) })}</b> {t('Ответы моделей разошлись, выберите верный.')}
          </span>
          {qa() && (
            <span className="flex flex-wrap gap-2">
              <Button size="sm" data-act="review" data-cid={c.id} data-val={String(r.a)} onClick={() => ctx.review(c, r.a)}>
                {t('Оставить {a}', { a: ansTxt(c, r.a) })}
              </Button>
              <Button size="sm" data-act="review" data-cid={c.id} data-val={String(r.alt)} onClick={() => ctx.review(c, r.alt)}>
                {t('Принять {a}', { a: ansTxt(c, r.alt) })}
              </Button>
            </span>
          )}
        </Note>
      ) : (
        r.alt != null &&
        r.alt === r.a && (
          <p className="text-xs text-muted">{t('Второе мнение совпало: {a}.', { a: ansTxt(c, r.alt) })}</p>
        )
      )}
      {r.better && f != null && f < 1 && (
        <Note kind="better">
          <p>
            <b>{t('Как сказать лучше:')}</b> «{r.better}»
          </p>
        </Note>
      )}
    </>
  );
}
