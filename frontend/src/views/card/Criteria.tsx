// Оценка по критериям: секции, блок критерия [data-cid] с переключателем aria-expanded, балл «7,5 / 15»,
// обоснование, основания с переходом к реплике, второе мнение, N/A, история решений, ручной ответ и апелляция.
import { ChevronDown } from 'lucide-react';
import { ansTxt, f2, fn, mmss } from '../../lib/format.js';
import { allowed } from '../../lib/appeal.js';
import { byJev } from '../../lib/queue.js';
import { ans, calc, flagWhy, frac, lastDec } from '../../lib/scoring.js';
import { href } from '../../lib/router.js';
import { S } from '../../store';
import { Button, Chip, cn } from '../../ui';
import { OrgPlayer } from './Transcript';
import { lineBy, MANUAL, ptsTxt, tone } from './util';

export const ALL = '*'; // S.open[dialog]: раскрыты все критерии
const WHO: Record<string, string> = { client: 'клиент', operator: 'оператор', bot: 'бот', system: 'система' };

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

export function Criteria({ ctx, sum }: { ctx: Ctx; sum: any }) {
  const cl = S.checklist;
  return (
    <>
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
  let chip, pts;
  if (c.type === 'flag') {
    const on = a && Object.values(a).some(Boolean);
    chip = !r ? <Chip tone="ev">ждёт оценки</Chip> : on ? <Chip tone="risk">Да</Chip> : <Chip tone="ok">Нет</Chip>;
    pts = 'без баллов';
  } else {
    chip = <Chip tone={tone(c, a)}>{ansTxt(c, a)}</Chip>;
    pts = ptsTxt(c, a);
  }
  return (
    <article
      className={cn('crit border-b border-line2', isOpen && 'open bg-sunken')}
      data-cid={c.id}
      data-ev={(r?.ev || []).join(',')}
      onMouseEnter={() => ctx.hover(c.id)}
      onMouseLeave={() => ctx.hover(null)}
      onFocus={() => ctx.hover(c.id)}
    >
      <button
        type="button"
        className="crit-row grid w-full grid-cols-[2.2rem_minmax(0,1fr)_auto_auto_18px] items-center gap-2 px-4 py-2.5 text-left hover:bg-hover"
        data-act="crit"
        data-cid={c.id}
        aria-expanded={isOpen}
        onClick={() => ctx.toggle(c.id)}
      >
        <span className="text-[13px] text-muted">{c.id}</span>
        <span className="min-w-0">{c.name}</span>
        {chip}
        <span className="num text-[13px] font-semibold">{pts}</span>
        <ChevronDown size={16} className={cn('text-muted transition-transform', isOpen && 'rotate-180')} aria-hidden="true" />
      </button>
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
      <div className="box ev flex flex-col gap-2">
        <span>Критерий ждёт оценки. Пока итог считается без него.</span>
        {qa() && (
          <span>
            <Button size="sm" data-act="manual" data-cid={c.id} onClick={() => ctx.manual(c)}>
              Оценить вручную
            </Button>
          </span>
        )}
      </div>
    );
  const hist = S.appeals.filter((x: any) => x.dlg === d.id && x.cid === c.id && (x.status === 'confirmed' || x.status === 'changed'));
  const pa = S.appeals.find((x: any) => x.dlg === d.id && x.cid === c.id && x.status === 'pending');
  const blocked = S.appeals.some((x: any) => x.dlg === d.id && x.cid === c.id && x.status !== 'closed');
  return (
    <>
      {c.type === 'flag' ? <FlagBody c={c} r={r} a={a} ctx={ctx} /> : <ScoredBody c={c} r={r} a={a} ctx={ctx} />}
      {hist.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label>История оценки</Label>
          <div className="hist grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 text-[13px]">
            <span className="text-muted">Исходная</span>
            <span>Модель, {d.at}</span>
            <Chip tone="na">{ansTxt(c, r.a)}</Chip>
            {hist.map((h: any) => (
              <Hist key={h.id} c={c} h={h} />
            ))}
            {c.type !== 'flag' && (
              <>
                <span className="text-muted">Итог</span>
                <span>
                  Пересчитан по формуле чек-листа, было{' '}
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
          {r.model === MANUAL && <Chip tone="info">Поставлено вручную</Chip>}
          {!blocked && qa() && (
            <Button size="sm" data-act="manual" data-cid={c.id} onClick={() => ctx.manual(c)} title="Ручной ответ заменяет ответ модели">
              Изменить ответ
            </Button>
          )}
        </div>
      )}
      {pa ? (
        <p className="flex items-center gap-2">
          <Chip tone="info">Апелляция на рассмотрении</Chip>
          <a href={href('appeals', pa.id)} className="text-[13px]">
            Открыть
          </a>
        </p>
      ) : (
        S.role !== 'reviewer' && (
          <div>
            <Button data-act="appeal" data-cid={c.id} onClick={() => ctx.appeal(c.id)} title="Подать апелляцию: проверяющий решит, какой ответ верный">
              Оспорить оценку
            </Button>
          </div>
        )
      )}
    </>
  );
}

const Hist = ({ c, h }: { c: any; h: any }) => (
  <>
    <span className="text-muted">{h.kind === 'appeal' ? 'Апелляция' : 'Решение'}</span>
    <span>
      {h.reviewer}, {h.decidedAt}: «{h.reason}»
    </span>
    <Chip tone={h.status === 'changed' ? 'info' : 'ok'}>{h.status === 'changed' ? ansTxt(c, h.to) : 'подтверждено'}</Chip>
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
          <div key={n} className="quote flex flex-wrap items-start justify-between gap-2 rounded-lg border-l-[3px] border-line-strong bg-surface px-3 py-2">
            <div className="min-w-0 flex-1">
              <span className="text-xs text-muted">
                {n}, {WHO[l.who] || l.who}
              </span>
              <br />«{l.text}»
            </div>
            <span className="flex gap-1.5">
              <Button size="sm" data-act="ev" data-n={n} onClick={() => ctx.jump(n)}>
                К реплике
              </Button>
              {call &&
                (l.s == null ? (
                  <OrgPlayer d={d} />
                ) : (
                  <Button size="sm" data-act="seek" data-n={l.n} onClick={() => ctx.seekLine(l)} aria-label={`Перейти к фрагменту, ${mmss(l.s)}`} title="Перейти к фрагменту">
                    ▶ {mmss(l.s)}
                  </Button>
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
              {a[x.q.k] ? <Chip tone="risk">найдено</Chip> : <span className="text-[13px] text-muted">нет</span>}
            </div>
            {x.why && <p className="text-[13px]">{x.why}</p>}
            <Evidence ev={x.ev} ctx={ctx} />
          </div>
        ))}
      </div>
      {fw.rest && <p>{fw.rest}</p>}
      {fw.ev.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label>Основание</Label>
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
  const vals = allowed(c).filter((v: any) => v !== 'na' || a === 'na' || r.alt === 'na');
  const altDiff = r.alt != null && r.alt !== a;
  const dec = lastDec(d, c.id, S.appeals);
  const txt = (v: any) => (v === 'yes' ? 'Да' : v === 'no' ? 'Нет' : v === 'na' ? 'N/A' : v);
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <div className="ladder flex flex-wrap gap-1" role="img" aria-label={`Ответ ${ansTxt(c, a)}${altDiff ? `, второе мнение ${ansTxt(c, r.alt)}` : ''}`}>
          {vals.map((v: any) => (
            <span
              key={v}
              className={cn(
                'step min-w-9 rounded-md border px-2 py-0.5 text-center text-[13px]',
                v === a ? 'on border-accent bg-accent font-semibold text-on-accent' : altDiff && v === r.alt ? 'alt border-dashed border-info text-info' : 'border-line text-muted',
              )}
            >
              {txt(v)}
            </span>
          ))}
        </div>
        {c.type === 'scale' && c.stepText && c.stepText[a] && (
          <span className="text-xs text-muted">
            {a}: {c.stepText[a]}
          </span>
        )}
      </div>
      {a === 'na' ? (
        <div className="box na" title="N/A: критерий неприменим к разговору, его вес делится между остальными">
          <b>Условие N/A выполнено.</b> {c.naCond} {r.why} Вес {c.w} распределён между применимыми критериями.
        </div>
      ) : (
        <div>
          <Label>Обоснование</Label>
          <p>{r.why}</p>
        </div>
      )}
      {/* пропущенное действие: реплик-оснований нет, модель называет проверенный участок; Jev участок не называет */}
      {!byJev(r) && ((a === 'no' && (r.seg || !hasEv)) || (c.type === 'scale' && f != null && f < 1 && !hasEv)) && (
        <p className="text-[13px]">
          Проверен участок: <b>{r.seg || 'весь диалог'}</b>. {a === 'no' ? 'Ожидаемого действия там нет.' : 'Полностью действие там не выполнено.'}
        </p>
      )}
      {hasEv && (
        <div className="flex flex-col gap-1.5">
          <Label>Основание</Label>
          <Evidence ev={r.ev} ctx={ctx} />
        </div>
      )}
      {r.evFail && !dec && (
        <div className="box ev flex flex-col gap-2">
          <span>
            {byJev(r) ? (
              <>
                <b>Jev не уверен в ответе</b>: вероятность ниже порога.
              </>
            ) : (
              <>
                <b>Цитата не нашлась в указанной реплике</b> и после повтора.
              </>
            )}{' '}
            Ответ <Chip tone="ev">на проверку</Chip>
          </span>
          {qa() && (
            <span className="flex flex-wrap gap-2">
              <Button size="sm" data-act="review" data-cid={c.id} data-val={String(a)} onClick={() => ctx.review(c, a)}>
                Оставить {ansTxt(c, a)}
              </Button>
              <Button size="sm" data-act="review" data-cid={c.id} onClick={() => ctx.review(c, null)}>
                Изменить
              </Button>
            </span>
          )}
        </div>
      )}
      {r.alt != null && r.alt !== r.a && !dec ? (
        <div className="box info flex flex-col gap-2" title="Второе мнение: ответ второй модели. При расхождении решает специалист">
          <span>
            <b>Второе мнение: {ansTxt(c, r.alt)}.</b> Модели разошлись, ответ ждёт решения специалиста.
          </span>
          {qa() && (
            <span className="flex flex-wrap gap-2">
              <Button size="sm" data-act="review" data-cid={c.id} data-val={String(r.a)} onClick={() => ctx.review(c, r.a)}>
                Оставить {ansTxt(c, r.a)}
              </Button>
              <Button size="sm" data-act="review" data-cid={c.id} data-val={String(r.alt)} onClick={() => ctx.review(c, r.alt)}>
                Принять {ansTxt(c, r.alt)}
              </Button>
            </span>
          )}
        </div>
      ) : (
        r.alt != null && r.alt === r.a && <p className="text-xs text-muted">Второе мнение совпало: {ansTxt(c, r.alt)}.</p>
      )}
      {r.better && f != null && f < 1 && (
        <div className="box good">
          <b>Как сказать лучше:</b> «{r.better}»
        </div>
      )}
    </>
  );
}
