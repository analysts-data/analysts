// «Перепроверить ▾»: POST /api/runs с force, apply (replace | compare) и override (другая модель или настройки).
// Прогресс — опрос GET /api/runs/{id}; после «Только сравнить» открывается сравнение (views/Compare.tsx).
import * as M from '@radix-ui/react-dropdown-menu';
import { Check, ChevronDown } from 'lucide-react';
import { useEffect, useState } from 'react';
import { t } from '../../lib/i18n.js';
import { api, reload, runNote, toast } from '../../lib/state.js';
import { rerender, S as STATE, useS } from '../../store';
import { Button, Field, Modal, Tip } from '../../ui';
import { Compare } from '../Compare';

export type Apply = 'replace' | 'compare';
type Override = { evaluator?: string; llm_provider?: string; verifier?: string | null };

/** Что запуск не тронул: ручные ответы и решения (skipped), диалоги без достаточных данных (insufficient). */
export const skippedNote = (run: any) =>
  [
    run?.skipped > 0 && t('Пропущено: {n} (ручные ответы и решения).', { n: run.skipped }),
    run?.insufficient > 0 && t('Пропущено, недостаточно данных: {n}.', { n: run.insufficient }),
  ]
    .filter(Boolean)
    .join(' ');

// ponytail: свой опрос, как rerun в card/Ops.tsx, пока startRun (lib/state.js) не принимает force, apply и override.
export async function recheck(dialogs: string[], criteria: string[] | null, apply: Apply, override?: Override) {
  let run: any = null;
  try {
    const { run_id } = await api.post('/runs', { dialogs, criteria, force: true, apply, ...(override ? { override } : {}) });
    run = STATE.run = { id: run_id, done: 0, total: 0, cost: 0, calls: 0, eta_s: null, errors: [], status: 'running', dialogs: dialogs.map(id => ({ id, status: 'queued' })) };
    rerender();
    for (let wait = 0; run.status === 'running'; wait = 1000) {
      await new Promise(r => setTimeout(r, wait));
      Object.assign(run, await api.getRun(run_id));
      rerender();
    }
  } catch (e: any) {
    if (run) STATE.run = null;
    toast(run ? t('Прогресс оценки недоступен: {err}', { err: e.message }) : t('Перепроверка не запущена: {err}', { err: e.message }));
    rerender();
    return null;
  }
  toast([runNote(run), skippedNote(run)].filter(Boolean).join(' '));
  await reload();
  return run;
}

const APPLY = (): [Apply, string, string][] => [
  ['compare', t('Только сравнить'), t('Новые ответы не меняют итог, пока вы их не примете.')],
  ['replace', t('Заменить текущую оценку'), t('Новые ответы сразу считают итог, прежние остаются в истории.')],
];

/** «Другой моделью…» (full = false) и «С другими настройками…»: оценщик, основная модель, второе мнение. */
function Settings({ full, apply, onRun, onClose }: { full: boolean; apply: Apply; onRun: (o: Override, a: Apply) => void; onClose: () => void }) {
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api.getConfig().then(setCfg, (e: any) => {
      toast(t('Режим не загружен: {error}', { error: e.message }));
      onClose();
    });
  }, []);
  const providers: any[] = (cfg?.providers || []).filter((p: any) => full || p.id !== cfg.llm_provider);
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const o: Override = { llm_provider: String(f.get('llm_provider') || '') || undefined };
    if (full) Object.assign(o, { evaluator: String(f.get('evaluator')), verifier: String(f.get('verifier') || '') || null });
    onRun(o, f.get('apply') as Apply);
  };
  return (
    <Modal
      open
      onOpenChange={v => !v && onClose()}
      title={full ? t('Перепроверить с другими настройками') : t('Перепроверить другой моделью')}
      description={t('Настройки действуют только на эту перепроверку, режим оценки не меняется.')}
    >
      {!cfg ? (
        <p className="text-muted">{t('Загружаем…')}</p>
      ) : (
        <form className="flex flex-col gap-4" onSubmit={submit}>
          {full && (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1.5 text-[13px] font-semibold text-ink2">{t('Оценщик')}</legend>
              {[
                ['llm', t('Языковая модель')],
                ['jev', t('Только Jev (быстро, без обоснований)')],
              ].map(([v, label]) => (
                <label key={v} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="evaluator" value={v} defaultChecked={v === (cfg.evaluator || 'llm')} />
                  {label}
                </label>
              ))}
            </fieldset>
          )}
          {providers.length ? (
            <Field label={t('Основная модель')}>
              <select name="llm_provider" className="fld w-full" required={!full} defaultValue={full ? cfg.llm_provider || '' : ''}>
                {!full && <option value="">{t('Выберите…')}</option>}
                {providers.map(p => (
                  <option key={p.id} value={p.id}>
                    {p.label || p.id}
                    {p.model ? ` · ${p.model}` : ''}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <p className="text-[13px] text-muted">{t('Других моделей нет. Добавьте модель в окне «Режим оценки».')}</p>
          )}
          {full && (
            <Field label={t('Второе мнение')}>
              <select name="verifier" className="fld w-full" defaultValue={cfg.verifier || ''}>
                <option value="">{t('нет')}</option>
                <option value="jev">Jev</option>
                {(cfg.providers || []).map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.label || p.id}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1.5 text-[13px] font-semibold text-ink2">{t('Результат')}</legend>
            {APPLY().map(([v, label, hint]) => (
              <label key={v} className="flex items-baseline gap-2 text-sm">
                <input type="radio" name="apply" value={v} defaultChecked={v === apply} />
                <span>
                  {label}
                  <span className="block text-xs text-muted">{hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="flex justify-end gap-2.5">
            <Button onClick={onClose}>{t('Отмена')}</Button>
            <Button type="submit" variant="primary" data-act="recheck-go" disabled={!full && !providers.length}>
              {t('Перепроверить')}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

const item = 'flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2.5 py-2 outline-none data-[highlighted]:bg-hover';

/** Кнопка с меню перепроверки. dialogs — диалоги запуска, criteria — критерии (null — все).
 * joined — только стрелка, приставленная справа к кнопке «Оценить заново». */
export function RecheckMenu({ dialogs, criteria = null, size, label, joined }: { dialogs: string[]; criteria?: string[] | null; size?: 'sm'; label?: string; joined?: boolean }) {
  const S = useS();
  const [apply, setApply] = useState<Apply>('compare');
  const [dlg, setDlg] = useState<'model' | 'full' | null>(null);
  const [busy, setBusy] = useState(false);
  const [cmp, setCmp] = useState<any>(null);
  const why = !dialogs.length ? t('Выберите диалоги.') : S.run?.status === 'running' && !busy ? t('Идёт оценка. Перепроверка станет доступна, когда она закончится.') : null;

  const go = async (override?: Override, mode: Apply = apply) => {
    setDlg(null);
    setBusy(true);
    const run = await recheck(dialogs, criteria, mode, override);
    setBusy(false);
    if (run && mode === 'compare' && run.total > 0) setCmp(run);
  };

  return (
    <>
      <M.Root modal={false}>
        <Tip content={why ?? (joined ? t('Перепроверить другой моделью или с другими настройками') : null)}>
          <span>
            <M.Trigger asChild disabled={busy || Boolean(why)}>
              <Button size={size} data-act="recheck" data-cid={criteria?.[0]} aria-busy={busy} aria-label={joined ? t('Перепроверить') : undefined} className={joined ? '-ml-px rounded-l-none !px-2.5' : undefined}>
                {joined ? null : busy ? t('Перепроверяется…') : label || t('Перепроверить')} <ChevronDown size={15} aria-hidden="true" />
              </Button>
            </M.Trigger>
          </span>
        </Tip>
        <M.Portal>
          <M.Content align="end" sideOffset={6} className="z-[70] min-w-[230px] rounded-lg border border-line bg-surface p-1 text-[13px] text-ink shadow-pop">
            <M.Item className={item} data-act="recheck-same" onSelect={() => go()}>
              {t('Той же моделью')}
            </M.Item>
            <M.Item className={item} data-act="recheck-model" onSelect={() => setDlg('model')}>
              {t('Другой моделью…')}
            </M.Item>
            <M.Item className={item} data-act="recheck-settings" onSelect={() => setDlg('full')}>
              {t('С другими настройками…')}
            </M.Item>
            <M.Separator className="my-1 h-px bg-line2" />
            <M.RadioGroup value={apply} onValueChange={v => setApply(v as Apply)}>
              {APPLY().map(([v, label]) => (
                <M.RadioItem key={v} value={v} className={item} data-apply={v} onSelect={e => e.preventDefault()}>
                  <span className="flex-1">{label}</span>
                  <M.ItemIndicator>
                    <Check size={15} className="text-accent" />
                  </M.ItemIndicator>
                </M.RadioItem>
              ))}
            </M.RadioGroup>
          </M.Content>
        </M.Portal>
      </M.Root>
      {dlg && <Settings full={dlg === 'full'} apply={apply} onRun={(o, a) => go(o, a)} onClose={() => setDlg(null)} />}
      {cmp && <Compare run={cmp} dialogs={dialogs} onClose={() => setCmp(null)} />}
    </>
  );
}
