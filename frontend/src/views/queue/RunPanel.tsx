// Панель «Оценка набора»: сводка без запуска, прогресс S.run (остаётся после done), ошибки по диалогам.
import { Play, Square } from 'lucide-react';
import { fn } from '../../lib/format.js';
import { href } from '../../lib/router.js';
import { cancelRun, failedDialogs, runNote, startRun } from '../../lib/state.js';
import { useS } from '../../store';
import { Button, Card } from '../../ui';
import { DIALOGS, plural, type Row } from './order';

function Bar({ pct, label }: { pct: number; label: string }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-hover" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <i className="block h-full rounded-full bg-accent transition-[width] duration-200" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Ошибки запуска одной фразой и список по диалогам; годится и для баннера чек-листа. */
export function RunErrors({ run }: { run: any }) {
  if (!run?.errors?.length) return null;
  const n = run.errors.length;
  const head = run.status === 'running' ? `Ошибок пока: ${n}, в диалогах: ${failedDialogs(run.errors).length}.` : runNote(run);
  return (
    <div className="box risk flex basis-full flex-col gap-1.5">
      <b>{head}</b>
      <details>
        <summary className="cursor-pointer">Показать ошибки ({n})</summary>
        <ul className="mt-1.5 list-disc pl-[18px] [overflow-wrap:anywhere]">
          {run.errors.map((e: string, i: number) => {
            const id = failedDialogs([e])[0];
            return (
              <li key={i}>
                <a href={href('d', id)}>{id}</a>
                {e.slice(id.length)}
              </li>
            );
          })}
        </ul>
      </details>
    </div>
  );
}

/** dialogs — идентификаторы видимых строк, null — весь набор. */
export function RunPanel({ all, dialogs, pending }: { all: Row[]; dialogs: string[] | null; pending: number }) {
  const S = useS();
  const run = S.run;
  const runBtn = (
    <Button variant="primary" data-act="run" onClick={() => startRun({ dialogs, criteria: null })}>
      <Play size={16} aria-hidden="true" /> {!pending ? 'Оценить' : dialogs ? `Оценить показанные: ${pending}` : `Оценить ${pending} ${plural(pending, DIALOGS)}`}
    </Button>
  );
  let body;
  if (!run) {
    // Без запуска — сводка набора: оценённые диалоги и стоимость из Dialog.cost как есть.
    const done = all.filter(x => !x.c.pending).length,
      n = all.length;
    const calls = S.dialogs.reduce((s: number, d: any) => s + (d.cost ? d.cost.calls + d.cost.verifier_calls : 0), 0);
    const usd = S.dialogs.reduce((s: number, d: any) => s + (d.cost ? d.cost.usd : 0), 0);
    body = (
      <>
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-2">
          <div className="flex flex-wrap justify-between gap-2">
            <span>
              <b>
                {done} из {n}
              </b>{' '}
              оценено по чек-листу v{S.checklist.version}
            </span>
            <span className="text-xs text-muted">
              {calls} вызовов, ${fn(usd)}
            </span>
          </div>
          <Bar pct={n ? (100 * done) / n : 0} label="Оценено диалогов" />
        </div>
        {runBtn}
      </>
    );
  } else {
    const state = run.status === 'running' ? 'Идёт оценка: ' : run.status === 'cancelled' ? 'Оценка остановлена: ' : 'Оценка завершена: ';
    const eta = run.eta_s != null && run.status === 'running' ? `, осталось около ${Math.ceil(run.eta_s)} с` : '';
    body = (
      <>
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-2">
          <div className="flex flex-wrap justify-between gap-2">
            <span id="runProgress" aria-live="polite">
              {state}
              {run.errors.length ? 'обработано' : 'оценено'}{' '}
              <b>
                {run.done} из {run.total}
              </b>{' '}
              ответов по критериям
            </span>
            <span className="text-xs text-muted">
              {run.calls} вызовов, ${fn(run.cost)}
              {eta}
              {run.errors.length ? `, ошибок: ${run.errors.length}` : ''}
            </span>
          </div>
          <Bar pct={run.total ? (100 * run.done) / run.total : 0} label="Прогресс оценки" />
        </div>
        {run.status === 'running' ? (
          <Button data-act="stop" onClick={() => cancelRun()}>
            <Square size={16} aria-hidden="true" /> Остановить
          </Button>
        ) : (
          runBtn
        )}
      </>
    );
  }
  return (
    <Card aria-label="Оценка набора" className="flex flex-wrap items-center gap-3 p-4">
      {body}
      <RunErrors run={run} />
    </Card>
  );
}
