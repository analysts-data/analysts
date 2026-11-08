// Экран решений по апелляциям (web/js/views/appeals.js): очередь слева, рассмотрение справа, история решений.
import { Play } from 'lucide-react';
import { useState } from 'react';
import { allowed, signOf } from '../lib/appeal.js';
import { ansTxt, f2, mmss, titleOf } from '../lib/format.js';
import { href } from '../lib/router.js';
import { calc } from '../lib/scoring.js';
import { api, reload, toast } from '../lib/state.js';
import { setRole, useS } from '../store';
import { Button, Card, Chip, cn, Empty, LinkButton, PageHead, type Tone } from '../ui';

const MIN_REASON = 5;
const WHO: Record<string, string> = { client: 'клиент', operator: 'оператор', bot: 'бот', system: 'система' };
const STATUS: Record<string, [Tone, string, string]> = {
  pending: ['ev', 'Ждёт решения', ''],
  changed: ['info', 'Оценка изменена', ', изменена'],
  confirmed: ['ok', 'Оценка подтверждена', ', подтверждена'],
  closed: ['na', 'Закрыта', ', закрыта'],
};
const step = (v: any) => (v === 'yes' ? 'Да' : v === 'no' ? 'Нет' : v === 'na' ? 'N/A' : String(v));

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
          <b className="truncate font-semibold">{d ? titleOf(d) : x.dlg}</b>
          <span className="flex-none text-xs text-muted">{x.at}</span>
        </span>
        <span className="text-[13px]">
          {x.cid} {c?.name}
        </span>
        <span className="text-xs text-muted">
          {txt(c, x.from)} → просят {txt(c, x.ask)}
          {STATUS[x.status]?.[2]}
        </span>
      </a>
    );
  };

  return (
    <>
      <PageHead title="Апелляции" sub="Спорная оценка, довод и фрагмент разговора на одном экране" />
      <div className="grid items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="flex flex-col p-2" aria-label="Очередь апелляций">
          <p className="px-3 pb-1.5 pt-1.5 text-xs font-semibold text-muted">Ждут решения: {pend.length}</p>
          {pend.map(item)}
          {!pend.length && <p className="px-3 pb-2 text-[13px] text-muted">Очередь пуста.</p>}
          <p className="px-3 pb-1.5 pt-3.5 text-xs font-semibold text-muted">Решённые: {done.length}</p>
          {done.map(item)}
        </Card>
        <div className="flex min-w-0 flex-col gap-4">
          {a ? (
            <Detail key={a.id} a={a} d={dlg(a.dlg)} c={crit(a.cid)} />
          ) : (
            <Card>
              <Empty action={<LinkButton href={href('queue')}>Открыть диалоги</LinkButton>}>Апелляций пока нет. Оспорить оценку можно в карточке разговора.</Empty>
            </Card>
          )}
          <Card className="p-5" aria-label="История решений">
            <h2 className="mb-2 text-base font-semibold">История решений</h2>
            {decided.length ? (
              <ol className="divide-y divide-line2">
                {decided.map((x: any) => {
                  const c = crit(x.cid), d = dlg(x.dlg);
                  return (
                    <li key={x.id} className="py-2.5 first:pt-0 last:pb-0">
                      <b className="font-semibold">
                        {d ? titleOf(d) : x.dlg}, {x.cid}: {x.status === 'changed' ? `${txt(c, x.from)} → ${txt(c, x.to)}` : 'оценка подтверждена'}
                      </b>
                      <p className="text-[13px] text-muted">
                        {x.reviewer}, {x.decidedAt}. {x.reason}
                      </p>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="text-[13px] text-muted">Решений пока нет.</p>
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
  if (!d.lines || !ns.length) return <p className="text-[13px] text-muted">Реплик-оснований нет.</p>;
  const lo = Math.min(...ns) - 2, hi = Math.max(...(mine.length ? mine : ns)) + 1;
  const shown = d.lines.filter((l: any) => !l.fold && ((l.n >= lo && l.n <= hi) || theirs.includes(l.n)));
  return (
    <div className="flex flex-col gap-1.5">
      {shown.map((l: any) => {
        const m = mine.includes(l.n), ap = theirs.includes(l.n);
        return (
          <div key={l.n} className={cn('flex items-start justify-between gap-3 rounded-lg px-3 py-2', m ? 'bg-ev-soft' : ap ? 'bg-hover' : '')}>
            <div className="min-w-0">
              <span className="text-xs text-muted">
                {l.n}, {WHO[l.who] || ''}
                {m && ', основание модели'}
                {ap && ', довод оспаривающего'}
              </span>
              <p>{l.text}</p>
            </div>
            {d.ch === 'call' && l.s != null && (
              <LinkButton size="sm" href={href('d', d.id)} title="Открыть карточку и прослушать запись">
                <Play size={13} aria-hidden="true" /> {mmss(l.s)}
              </LinkButton>
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
      <Card className="p-5" aria-label="Рассмотрение">
        <Empty>Критерий {a.cid} удалён из чек-листа или диалог не найден. Апелляция закрыта без решения.</Empty>
      </Card>
    );
  const r = d.res[a.cid] || {};
  const [tone, label] = STATUS[a.status] || STATUS.closed;
  return (
    <Card className="divide-y divide-line2" aria-label="Рассмотрение">
      <div className="flex flex-wrap items-start justify-between gap-3 p-5">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">
            {titleOf(d)}, {c.id} {c.name}
          </h2>
          <p className="text-[13px] text-muted">
            Подал: {a.by}, {a.at}. Вес критерия {c.w}. <a href={href('d', d.id)}>Открыть карточку</a>
          </p>
        </div>
        <Chip tone={tone}>{label}</Chip>
      </div>
      <div className="compare grid gap-5 p-5 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-muted">Оценка модели</span>
          <strong className="text-lg">{ansTxt(c, a.from)}</strong>
          {r.why && <span className="text-[13px] text-ink2">{r.why}</span>}
          {r.alt != null && (
            <span className="text-[13px] text-info" title="Ответ второй модели. Расхождение: повод проверить внимательнее">
              Второе мнение: {ansTxt(c, r.alt)}
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1 sm:border-l sm:border-line2 sm:pl-5">
          <span className="text-xs font-semibold text-muted">Просит оспаривающий</span>
          <strong className="text-lg">{ansTxt(c, a.ask)}</strong>
          <span className="text-[13px] text-ink2">«{a.comment}»</span>
        </div>
      </div>
      <div className="flex flex-col gap-1.5 p-5">
        <span className="text-xs font-semibold text-muted" title="Жёлтым: реплики, на которые опиралась модель. Серым: реплика из довода">
          Фрагмент разговора
        </span>
        <Fragment d={d} r={r} a={a} />
      </div>
      <div className="p-5">
        {a.status === 'closed' ? (
          <p className="text-muted">Критерий изменён или удалён новой версией чек-листа. Апелляция закрыта без решения.</p>
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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-muted">Решение принимает проверяющий. Переключите роль, чтобы показать этот шаг.</span>
            <Button size="sm" onClick={() => setRole('reviewer')}>
              Стать проверяющим
            </Button>
          </div>
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
      toast(`Решение не сохранено: ${e.message}`);
      return;
    }
    await reload();
    const nd = S.dialogs.find((x: any) => x.id === d.id) || d;
    toast(`Решение сохранено. Итог ${titleOf(nd)}: ${f2(before)} → ${f2(calc(nd, S.checklist, S.appeals).total)}.`);
  }

  return (
    <fieldset className="flex flex-col gap-4">
      <legend className="mb-2.5 text-base font-semibold">Решение проверяющего</legend>
      <div className="flex flex-wrap gap-2.5">
        {(
          [
            ['confirm', 'Подтвердить оценку модели'],
            ['change', 'Изменить оценку'],
          ] as const
        ).map(([v, t]) => (
          <label key={v} className={cn('flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border px-3', mode === v ? 'border-accent bg-accent-soft' : 'border-line hover:bg-hover')}>
            <input type="radio" name="dm" value={v} data-act="dmode" data-id={a.id} checked={mode === v} onChange={() => setMode(v)} className="accent-[var(--accent)]" />
            {t}
          </label>
        ))}
      </div>
      {mode === 'change' && flag && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink2">Нарушения после решения</span>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Нарушения после решения">
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
          <span className="text-xs text-muted">Нажатая кнопка: нарушение есть. Флаг в итог не входит.</span>
        </div>
      )}
      {mode === 'change' && !flag && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink2">Новый ответ</span>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Новый ответ">
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
            Доступны только {c.type === 'scale' ? 'ступени шкалы' : 'ответы «Да» и «Нет»'}
            {c.na ? ' и N/A, он разрешён у этого критерия' : ''}.
          </span>
        </div>
      )}
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-ink2">Причина решения, обязательно</span>
        <textarea
          className="fld"
          data-act="dreason"
          data-id={a.id}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="Например: регламент не позволяет называть срок, следующий шаг дан полностью"
        />
        <span className="text-xs text-muted">Не короче {MIN_REASON} символов. Причину увидят оспаривающий и оператор в карточке.</span>
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {flag ? (
          <span>Итог не меняется: {f2(before)}, флаг в сумму не входит</span>
        ) : (
          <span>
            Итог разговора: <s className="text-muted">{f2(before)}</s> → <b className="text-xl">{f2(after)}</b>
          </span>
        )}
        <Button variant="primary" data-act="decide" data-id={a.id} disabled={busy || reason.trim().length < MIN_REASON} onClick={decide}>
          Сохранить решение
        </Button>
      </div>
    </fieldset>
  );
}
