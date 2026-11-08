// Панель «Оценка набора»: сводка без запуска, прогресс S.run (остаётся после done), ошибки по диалогам,
// «Оценить заново» (POST /api/runs с force: ручные ответы и решения не перезаписываются, их число — skipped).
import { Play, RotateCcw, Square } from 'lucide-react';
import { useState } from 'react';
import { fn } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { href } from '../../lib/router.js';
import { api, cancelRun, failedDialogs, reload, resumeRun, runNote, startRun, toast } from '../../lib/state.js';
import { S as STATE, save, useS } from '../../store';
import { Button, Card, Modal } from '../../ui';
import { DIALOGS, plural, type Row } from './order';
import { InsufficientNote } from '../SufficiencyChip';

/**
 * Диалог в идущем прогоне ещё оценивается. Состояние по диалогам из GET /api/runs/{id} (`dialogs`: {id: status}
 * или [{id, status}]), если сервер его отдаёт; иначе — диалоги запуска (`scope`), которые ждут оценки, а при force — все.
 */
export function scoring(run: any, id: string, pending: boolean): boolean {
  if (run?.status !== 'running') return false;
  const st = Array.isArray(run.dialogs) ? run.dialogs.find((x: any) => x.id === id)?.status : run.dialogs?.[id];
  if (st) return st === 'queued' || st === 'running';
  if (Array.isArray(run.scope) && !run.scope.includes(id)) return false;
  return !!run.force || pending;
}

// startRun из lib/state.js не передаёт force: запуск здесь, опрос и итог — через resumeRun по ключу cqa.run.
async function rerun(dialogs: string[] | null) {
  try {
    const { run_id } = await api.post('/runs', { dialogs, criteria: null, force: true });
    toast(t('Оценка заново запущена. Ручные ответы и решения по апелляциям останутся.'));
    save('cqa.run', String(run_id));
    await resumeRun();
    if (STATE.run?.status === 'running' && String(STATE.run.id) === String(run_id)) Object.assign(STATE.run, { scope: dialogs, force: true });
    else {
      // запуск закончился раньше первого опроса: итог сразу
      STATE.run = { id: run_id, ...(await api.getRun(run_id)) };
      toast(runNote(STATE.run));
      await reload();
    }
  } catch (e: any) {
    toast(t('Оценка не запущена: {e}', { e: e.message }));
  }
}

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
  const head = run.status === 'running' ? t('Ошибок пока: {n}, в диалогах: {m}.', { n, m: failedDialogs(run.errors).length }) : runNote(run);
  return (
    <div className="box risk flex basis-full flex-col gap-1.5">
      <b>{head}</b>
      <details>
        <summary className="cursor-pointer">{t('Показать ошибки ({n})', { n })}</summary>
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
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  // защита от двойного клика: кнопки неактивны, пока идёт запрос
  const act = async (f: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await f();
    } finally {
      setBusy(false);
    }
  };
  // ponytail: при нуле неоценённых кнопка активна, но не основная: e2e запускают оценку на полностью оценённом наборе; disabled, когда у них будет фикстура с неоценёнными
  const runBtn = (
    <>
      {!pending && <span className="text-[13px] text-muted">{t('Всё оценено')}</span>}
      <Button
        variant={pending ? 'primary' : 'default'}
        data-act="run"
        disabled={busy}
        onClick={() =>
          act(async () => {
            await startRun({ dialogs, criteria: null });
            if (S.run?.status === 'running') S.run.scope = dialogs;
          })
        }
      >
        <Play size={16} aria-hidden="true" /> {!pending ? t('Оценить') : dialogs ? t('Оценить показанные: {n}', { n: pending }) : t('Оценить {n} {w}', { n: pending, w: plural(pending, DIALOGS()) })}
      </Button>
    </>
  );
  const n = dialogs ? dialogs.length : all.length;
  const scored = all.some(x => !x.c.pending);
  // весь набор — подтверждение: модель заново оценит все диалоги; показанные — сразу
  const rerunBtn = scored && n > 0 && (
    <Button data-act="rerun" disabled={busy} onClick={() => (dialogs ? act(() => rerun(dialogs)) : setConfirm(true))}>
      <RotateCcw size={16} aria-hidden="true" /> {dialogs ? t('Оценить заново показанные: {n}', { n }) : t('Оценить заново')}
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
              <b>{t('{done} из {total}', { done, total: n })}</b> {t('оценено по чек-листу v{v}', { v: S.checklist.version })}
            </span>
            <span className="text-xs text-muted">{t('{calls} вызовов, ${usd}', { calls, usd: fn(usd) })}</span>
          </div>
          <Bar pct={n ? (100 * done) / n : 0} label={t('Оценено диалогов')} />
        </div>
        {rerunBtn}
        {runBtn}
      </>
    );
  } else {
    const state = run.status === 'running' ? t('Идёт оценка:') : run.status === 'cancelled' ? t('Оценка остановлена:') : t('Оценка завершена:');
    const eta = run.eta_s != null && run.status === 'running' ? t(', осталось около {s} с', { s: Math.ceil(run.eta_s) }) : '';
    body = (
      <>
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-2">
          <div className="flex flex-wrap justify-between gap-2">
            <span id="runProgress" aria-live="polite">
              {state} {run.errors.length ? t('обработано') : t('оценено')} <b>{t('{done} из {total}', { done: run.done, total: run.total })}</b> {t('ответов по критериям')}
            </span>
            <span className="text-xs text-muted">
              {t('{calls} вызовов, ${usd}', { calls: run.calls, usd: fn(run.cost) })}
              {eta}
              {run.errors.length ? t(', ошибок: {n}', { n: run.errors.length }) : ''}
            </span>
            <InsufficientNote run={run} />
            {run.skipped > 0 && <span className="basis-full text-xs text-muted">{t('Не перезаписаны ручные ответы и ответы с апелляцией: {n}', { n: run.skipped })}</span>}
          </div>
          <Bar pct={run.total ? (100 * run.done) / run.total : 0} label={t('Прогресс оценки')} />
        </div>
        {run.status === 'running' ? (
          <Button data-act="stop" onClick={() => cancelRun()}>
            <Square size={16} aria-hidden="true" /> {t('Остановить')}
          </Button>
        ) : (
          <>
            {rerunBtn}
            {runBtn}
          </>
        )}
      </>
    );
  }
  return (
    <Card aria-label={t('Оценка набора')} className="flex flex-wrap items-center gap-3 p-4">
      {body}
      <RunErrors run={run} />
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title={t('Оценить заново весь набор?')}
        description={t('Модель заново оценит {n} {w}. Ручные ответы специалиста и ответы с апелляцией не перезапишутся, прежние ответы останутся в истории.', { n, w: plural(n, DIALOGS()) })}
      >
        <div className="flex justify-end gap-2.5">
          <Button onClick={() => setConfirm(false)}>{t('Отмена')}</Button>
          <Button
            variant="primary"
            data-act="rerun-all"
            disabled={busy}
            onClick={() =>
              act(async () => {
                setConfirm(false);
                await rerun(null);
              })
            }
          >
            {t('Оценить заново: {n} {w}', { n, w: plural(n, DIALOGS()) })}
          </Button>
        </div>
      </Modal>
    </Card>
  );
}
