// Экран решений по апелляциям (web/js/views/appeals.js): очередь слева, рассмотрение справа, история решений.
import { Play } from 'lucide-react';
import { useState } from 'react';
import { allowed, signOf } from '../lib/appeal.js';
import { ansTxt, f2, mmss, titleOf } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { calc } from '../lib/scoring.js';
import { api, reload, toast } from '../lib/state.js';
import { setRole, useS } from '../store';
import { Term } from '../terms';
import { Button, Card, Chip, cn, Empty, LinkButton, PageHead, Tip, type Tone } from '../ui';
import { humanError } from './AppealDialog';

const MIN_REASON = 5;
// Подписи — функции, а не константы: t() вызывается при отрисовке, после выбора языка.
const who = (w: string) => (({ client: t('клиент'), operator: t('оператор'), bot: t('бот'), system: t('система') }) as Record<string, string>)[w];
const status = (s: string) =>
  (({
    pending: ['ev', t('Ждёт решения'), ''],
    changed: ['info', t('Оценка изменена'), t(', изменена')],
    confirmed: ['ok', t('Оценка подтверждена'), t(', подтверждена')],
    closed: ['na', t('Закрыта'), t(', закрыта')],
  }) as Record<string, [Tone, string, string]>)[s];
const sub = (role: string) =>
  (({
    reviewer: t('Сравните оценку с доводом и фрагментом диалога, затем сохраните решение с причиной.'),
    operator: t('Апелляции по оценкам и решения проверяющего.'),
    qa: t('Спорная оценка, довод и фрагмент диалога на одном экране.'),
  }) as Record<string, string>)[role];
// «Оператор» → «оператор» для «Просит оператор», «как просит оператор».
const low = (by: string) => (by ? by[0].toLowerCase() + by.slice(1) : t('оператор'));
const same = (x: any, y: any) => JSON.stringify(x) === JSON.stringify(y);
const step = (v: any) => (v === 'yes' ? t('Да') : v === 'no' ? t('Нет') : v === 'na' ? 'N/A' : String(v));

export function Appeals({ id }: { id: string | null }) {
  const S = useS();
  const crit = (cid: string) => S.checklist?.criteria.find((c: any) => c.id === cid);
  const dlg = (did: string) => S.dialogs.find((d: any) => d.id === did);
  const txt = (c: any, v: any) => (c ? ansTxt(c, v) : String(v));
  const list = S.appeals.filter((a: any) => a.kind === 'appeal');
  const pend = list.filter((a: any) => a.status === 'pending');
  const done = list.filter((a: any) => a.status !== 'pending');
  const a = list.find((x: any) => x.id === id) || pend[0] || done[0];
  const decided = S.appeals
    .filter((x: any) => x.status === 'changed' || x.status === 'confirmed')
    .sort((x: any, y: any) => (y.decidedAt || '').localeCompare(x.decidedAt || ''));

  const item = (x: any) => {
    const c = crit(x.cid), d = dlg(x.dlg), on = a === x;
    return (
      <a
        key={x.id}
        href={href('appeals', x.id)}
        aria-current={on}
        className={cn('flex flex-col gap-0.5 rounded-lg px-3 py-2.5 text-ink no-underline transition-colors hover:text-ink', on ? 'bg-accent-soft' : 'hover:bg-hover')}
      >
        <span className="flex items-baseline justify-between gap-2">
          <Tip content={d ? titleOf(d) : x.dlg}>
            <b className="truncate font-semibold">{d ? titleOf(d) : x.dlg}</b>
          </Tip>
          <span className="flex-none text-xs text-muted">{x.at}</span>
        </span>
        <span className="text-[13px]">
          {x.cid} {c?.name}
        </span>
        <span className="text-xs text-muted">
          {t('{from} → просят {ask}', { from: txt(c, x.from), ask: txt(c, x.ask) })}
          {status(x.status)?.[2]}
        </span>
      </a>
    );
  };

  // пусто: одна карточка вместо очереди, «ждут решения 0» и пустой истории
  if (!list.length)
    return (
      <>
        <PageHead title={t('Апелляции')} sub={sub(S.role)} />
        <Card>
          <Empty action={<LinkButton href={href('queue')}>{t('Перейти к диалогам')}</LinkButton>}>
            {S.role === 'operator' ? t('Апелляций нет. Не согласны с оценкой: откройте диалог и нажмите «Оспорить».') : t('Апелляций нет. Они появятся, когда оператор оспорит оценку.')}
          </Empty>
        </Card>
      </>
    );

  return (
    <>
      <PageHead title={S.role === 'reviewer' ? t('Апелляции: ждут решения {n}', { n: pend.length }) : t('Апелляции')} sub={sub(S.role)} />
      <div className="grid items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="flex flex-col p-2" aria-label={t('Очередь апелляций')}>
          <p className="px-3 pb-1.5 pt-1.5 text-xs font-semibold text-muted">{t('Ждут решения: {n}', { n: pend.length })}</p>
          {pend.map(item)}
          {!pend.length && <p className="px-3 pb-2 text-[13px] text-muted">{t('Очередь пуста.')}</p>}
          <p className="px-3 pb-1.5 pt-3.5 text-xs font-semibold text-muted">{t('Решённые: {n}', { n: done.length })}</p>
          {done.map(item)}
        </Card>
        <div className="flex min-w-0 flex-col gap-4">
          <Detail key={a.id} a={a} d={dlg(a.dlg)} c={crit(a.cid)} />
          <Card className="p-5" aria-label={t('История решений')}>
            <h2 className="mb-2 text-base font-semibold">{t('История решений')}</h2>
            {decided.length ? (
              <ol className="divide-y divide-line2">
                {decided.map((x: any) => {
                  const c = crit(x.cid), d = dlg(x.dlg);
                  return (
                    <li key={x.id} className="py-2.5 first:pt-0 last:pb-0">
                      <b className="font-semibold">
                        {d ? titleOf(d) : x.dlg},{' '}
                        <Tip content={c?.name}>
                          <span tabIndex={0}>{x.cid}</span>
                        </Tip>
                        : {x.status === 'changed' ? `${txt(c, x.from)} → ${txt(c, x.to)}` : t('оценка подтверждена')}
                      </b>
                      <p className="text-[13px] text-muted">
                        {x.reviewer}, {x.decidedAt}. {x.reason}
                      </p>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="text-[13px] text-muted">{t('Решений пока нет.')}</p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function Fragment({ d, r, a }: { d: any; r: any; a: any }) {
  const mine: number[] = r.ev || [], theirs: number[] = a.ev || [];
  const ns = [...mine, ...theirs];
  if (!d.lines || !ns.length) return <p className="text-[13px] text-muted">{t('Реплик-оснований нет.')}</p>;
  const lo = Math.min(...ns) - 2, hi = Math.max(...(mine.length ? mine : ns)) + 1;
  const shown = d.lines.filter((l: any) => !l.fold && ((l.n >= lo && l.n <= hi) || theirs.includes(l.n)));
  return (
    <div className="flex flex-col gap-1.5">
      {shown.map((l: any) => {
        const m = mine.includes(l.n), ap = theirs.includes(l.n);
        return (
          <div key={l.n} className={cn('flex items-start justify-between gap-3 border-l-2 py-1 pl-3', m ? 'border-ev' : ap ? 'border-line-strong' : 'border-transparent')}>
            <div className="min-w-0">
              <span className="text-xs text-muted">
                {l.n}, {who(l.who) || ''}
                {m && t(', основание модели')}
                {ap && t(', из апелляции')}
              </span>
              <p>{l.text}</p>
            </div>
            {d.ch === 'call' && l.s != null && (
              <Tip content={t('Открыть карточку и прослушать запись с этой реплики')}>
                <span className="flex-none">
                  <LinkButton size="sm" href={href('d', d.id)} aria-label={t('Прослушать с {time} в карточке', { time: mmss(l.s) })}>
                    <Play size={14} aria-hidden="true" /> {mmss(l.s)}
                  </LinkButton>
                </span>
              </Tip>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Detail({ a, d, c }: { a: any; d: any; c: any }) {
  const S = useS();
  if (!d || !c)
    return (
      <Card className="p-5" aria-label={t('Рассмотрение')}>
        <Empty>{t('Критерий {cid} удалён из чек-листа или диалог не найден. Апелляция закрыта без решения.', { cid: a.cid })}</Empty>
      </Card>
    );
  const r = d.res[a.cid] || {};
  const [tone, label] = status(a.status) || status('closed');
  return (
    <Card className="divide-y divide-line2" aria-label={t('Рассмотрение')}>
      <div className="flex flex-wrap items-start justify-between gap-3 p-5">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">
            {titleOf(d)}, {c.id} {c.name}
          </h2>
          <p className="text-[13px] text-muted">
            {t('Подал: {by}, {at}. Вес критерия {w}.', { by: a.by, at: a.at, w: c.w })} <a href={href('d', d.id)}>{t('Открыть карточку')}</a>
          </p>
        </div>
        <Chip tone={tone}>{label}</Chip>
      </div>
      <div className="compare grid gap-5 p-5 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-muted">{a.status === 'pending' ? t('Сейчас') : t('Было')}</span>
          <strong className="text-lg">{ansTxt(c, a.from)}</strong>
          {r.why && <span className="text-[13px] text-ink2">{r.why}</span>}
          {r.alt != null && (
            <span className="text-[13px] text-info">
              <Term k="second">{t('Второе мнение')}</Term>: {ansTxt(c, r.alt)}
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1 sm:border-l sm:border-line2 sm:pl-5">
          <span className="text-xs font-semibold text-muted">{t('Просит {who}', { who: low(a.by) })}</span>
          <strong className="text-lg">{ansTxt(c, a.ask)}</strong>
          <span className="text-[13px] text-ink2">«{a.comment}»</span>
        </div>
      </div>
      <div className="flex flex-col gap-1.5 p-5">
        <span className="text-xs font-semibold text-muted">{t('Фрагмент диалога')}</span>
        <Fragment d={d} r={r} a={a} />
      </div>
      <div className="p-5">
        {a.status === 'closed' ? (
          <p className="text-muted">{t('Критерий изменён или удалён новой версией чек-листа. Апелляция закрыта без решения.')}</p>
        ) : a.status !== 'pending' ? (
          <p>
            <b className="font-semibold">
              {a.reviewer}, {a.decidedAt}:
            </b>{' '}
            {a.reason}
          </p>
        ) : S.role === 'reviewer' ? (
          <Decision a={a} d={d} c={c} />
        ) : (
          <p className="text-muted">
            {t('Апелляцию рассматривает проверяющий. Когда он примет решение, статус сменится на «Оценка изменена» или «Оценка подтверждена».')}
            {S.role === 'qa' && (
              <>
                {' '}
                <button type="button" className="font-semibold text-accent hover:text-accent-ink hover:underline" onClick={() => setRole('reviewer')}>
                  {t('Смотреть как проверяющий')}
                </button>
              </>
            )}
          </p>
        )}
      </div>
    </Card>
  );
}

function Decision({ a, d, c }: { a: any; d: any; c: any }) {
  const S = useS();
  const [mode, setMode] = useState<'change' | 'confirm'>('change');
  const [val, setVal] = useState<any>(a.ask);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const to = mode === 'confirm' ? a.from : val;
  const before = calc(d, S.checklist, S.appeals).total;
  const after = calc(d, S.checklist, S.appeals, { cid: a.cid, val: to }).total;
  const flag = c.type === 'flag';
  const pick = 'min-h-9 rounded-lg border px-3 text-[13px] font-semibold transition-colors';
  const on = (p: boolean) => (p ? 'border-accent bg-accent text-on-accent' : 'border-line-strong bg-surface text-ink2 hover:bg-hover');

  async function decide() {
    setBusy(true);
    try {
      await api.postDecision(a.id, { to, reason: reason.trim(), reviewer: signOf(S.role) });
    } catch (e: any) {
      setBusy(false);
      toast(t('Решение не сохранено. {err}', { err: humanError(e, { 409: t('Апелляция уже рассмотрена, на экране её решение.') }) }));
      if (e?.status === 409) await reload();
      return;
    }
    await reload();
    const nd = S.dialogs.find((x: any) => x.id === d.id) || d;
    const total = flag ? '' : ` ${t('Итог {title}: {before} → {after}.', { title: titleOf(nd), before: f2(before), after: f2(calc(nd, S.checklist, S.appeals).total) })}`;
    const what = same(to, a.from) ? t('оценка «{ans}» подтверждена.', { ans: ansTxt(c, to) }) : `${ansTxt(c, a.from)} → ${ansTxt(c, to)}.`;
    toast(t('Решение сохранено: {what}{total} {who} увидит решение в карточке.', { what, total, who: a.by || t('Оператор') }));
  }

  return (
    <fieldset className="flex flex-col gap-4">
      <legend className="mb-2.5 text-base font-semibold">
        <Term k="decision">{t('Решение по апелляции')}</Term>
      </legend>
      <div className="flex flex-wrap gap-2.5">
        {(
          [
            ['confirm', t('Подтвердить оценку модели «{ans}»', { ans: ansTxt(c, a.from) })],
            ['change', t('Изменить оценку на «{ans}»{tail}', { ans: ansTxt(c, val), tail: same(val, a.ask) ? t(', как просит {who}', { who: low(a.by) }) : '' })],
          ] as const
        ).map(([v, label]) => (
          <label key={v} className={cn('flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border px-3', mode === v ? 'border-accent bg-accent-soft' : 'border-line hover:bg-hover')}>
            <input type="radio" name="dm" value={v} data-act="dmode" data-id={a.id} checked={mode === v} onChange={() => setMode(v)} className="accent-[var(--accent)]" />
            {label}
          </label>
        ))}
      </div>
      {mode === 'change' && flag && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink2">{t('Нарушения после решения')}</span>
          <div className="flex flex-wrap gap-2" role="group" aria-label={t('Нарушения после решения')}>
            {(c.questions || []).map((q: any) => (
              <button
                key={q.k}
                type="button"
                className={cn(pick, on(!!val?.[q.k]))}
                data-act="dflag"
                data-id={a.id}
                data-k={q.k}
                aria-pressed={!!val?.[q.k]}
                onClick={() => setVal({ ...val, [q.k]: !val?.[q.k] })}
              >
                {q.label}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted">{t('Нажатая кнопка: нарушение есть. Грубые ошибки в итог не входят.')}</span>
        </div>
      )}
      {mode === 'change' && !flag && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink2">{t('Новый ответ')}</span>
          <div className="flex flex-wrap gap-2" role="group" aria-label={t('Новый ответ')}>
            {allowed(c).map((v: any) => (
              <button key={v} type="button" className={cn(pick, 'min-w-11', on(v === val))} data-act="dval" data-id={a.id} data-v={v} aria-pressed={v === val} onClick={() => setVal(v)}>
                {step(v)}
              </button>
            ))}
          </div>
          {c.type === 'scale' && c.stepText?.[val] && (
            <span className="text-xs text-muted">
              {val}: {c.stepText[val]}
            </span>
          )}
          <span className="text-xs text-muted">
            {t('Доступны только {what}{na}.', {
              what: c.type === 'scale' ? t('ступени шкалы') : t('ответы «Да» и «Нет»'),
              na: c.na ? t(' и N/A, он разрешён у этого критерия') : '',
            })}
          </span>
        </div>
      )}
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-ink2">{t('Причина решения, обязательно')}</span>
        <textarea
          className="fld"
          data-act="dreason"
          data-id={a.id}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder={t('Например: регламент не позволяет называть срок, следующий шаг дан полностью')}
        />
        <span className="text-xs text-muted">{t('Причина видна в карточке диалога рядом с исходной оценкой.')}</span>
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {flag ? (
          <span>{t('Итог не меняется: {total}. Грубые ошибки в итог не входят.', { total: f2(before) })}</span>
        ) : (
          <span>
            <Term k="total">{t('Итог')}</Term> {t('диалога:')} <s className="text-muted">{f2(before)}</s> → <b className="text-xl">{f2(after)}</b>
          </span>
        )}
        <span className="flex flex-wrap items-center justify-end gap-3">
          {reason.trim().length < MIN_REASON && <span className="text-xs text-muted">{t('Напишите причину решения, не короче {n} символов', { n: MIN_REASON })}</span>}
          <Button variant="primary" data-act="decide" data-id={a.id} disabled={busy || reason.trim().length < MIN_REASON} onClick={decide}>
            {t('Сохранить решение')}
          </Button>
        </span>
      </div>
    </fieldset>
  );
}
