// «Автоматизация»: главный выключатель, состояние цикла (GET /api/automation/status, опрос раз в 5 с), запуск и пауза,
// настройки синхронизации, оценки и шагов после неё (ошибки по полям из 422) и журнал циклов.
import { Download } from 'lucide-react';
import { useEffect, useState } from 'react';
import { t } from '../lib/i18n.js';
import { toast } from '../lib/state.js';
import { useS } from '../store';
import { Button, Card, Chip, cn, Field, PageHead, Skeleton, Tip, type Tone } from '../ui';
import { DownloadButton } from './people/net';
import { type Fields, send, usd, when } from './sources/net';

const STATE: Record<string, [() => string, Tone]> = {
  off: [() => t('Выключена'), 'na'],
  idle: [() => t('Ждёт следующего цикла'), 'ok'],
  syncing: [() => t('Забирает диалоги'), 'info'],
  evaluating: [() => t('Оценивает'), 'info'],
  paused: [() => t('На паузе'), 'ev'],
  budget_reached: [() => t('Бюджет на сегодня исчерпан'), 'risk'],
  quiet_hours: [() => t('Тихие часы'), 'na'],
};
const SKIP: Record<string, () => string> = {
  budget_reached: () => t('бюджет исчерпан'),
  quiet_hours: () => t('тихие часы'),
  hour_limit: () => t('лимит в час'),
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="grid gap-4 px-4 py-4 sm:grid-cols-2">
      <legend className="sr">{title}</legend>
      <h2 className="text-[15px] font-semibold sm:col-span-2">{title}</h2>
      {children}
    </fieldset>
  );
}

export function Automation(_: { id: string | null }) {
  const S = useS();
  const [cfg, setCfg] = useState<any>(null);
  const [form, setForm] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [cycles, setCycles] = useState<any[] | null>(null);
  const [sources, setSources] = useState<any[]>([]);
  const [errs, setErrs] = useState<Fields>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  const loadStatus = () => send('GET', '/automation/status').then(setStatus, () => {});
  useEffect(() => {
    send('GET', '/automation').then(
      c => (setCfg(c), setForm(c)),
      e => setError(e.message),
    );
    loadStatus();
    if (S.features?.includes('sources')) send('GET', '/sources').then(l => setSources(l.filter((s: any) => ['org_api', 'http_json'].includes(s.kind) && !s.archived)), () => {});
    const h = setInterval(loadStatus, 5000);
    return () => clearInterval(h);
  }, []);
  // новый цикл в состоянии — перечитать журнал
  useEffect(() => {
    send('GET', '/automation/cycles?limit=20').then(setCycles, () => setCycles([]));
  }, [status?.last_cycle?.started, status?.last_cycle?.finished]);

  const get = (p: string) => p.split('.').reduce((o: any, k) => o?.[k], form);
  const put = (p: string, v: unknown) =>
    setForm((f: any) => {
      const c = structuredClone(f);
      const ks = p.split('.');
      ks.slice(0, -1).reduce((o: any, k) => (o[k] ??= {}), c)[ks[ks.length - 1]] = v;
      return c;
    });
  const err = (p: string, hint?: string) => (errs[p] ? <span className="text-risk">{errs[p]}</span> : hint);
  const num = (p: string, label: string, hint?: string, step?: string) => (
    <Field label={label} hint={err(p, hint)}>
      <input className="fld w-36" type="number" min={step ? 0.01 : 1} step={step ?? 1} value={get(p) ?? ''} onChange={e => put(p, e.target.value === '' ? '' : Number(e.target.value))} aria-invalid={!!errs[p]} />
    </Field>
  );
  const chk = (p: string, label: string, hint?: string) => (
    <label className="flex items-start gap-2.5">
      <input type="checkbox" className="mt-1" checked={!!get(p)} onChange={e => put(p, e.target.checked)} />
      <span>
        <span className="block">{label}</span>
        {(errs[p] || hint) && <span className="block text-xs text-muted">{err(p, hint)}</span>}
      </span>
    </label>
  );

  async function toggle() {
    setBusy('toggle');
    try {
      const c = await send('PUT', '/automation', { ...cfg, enabled: !cfg.enabled });
      setCfg(c);
      setForm((f: any) => ({ ...f, enabled: c.enabled }));
      toast(c.enabled ? t('Автоматизация включена.') : t('Автоматизация выключена.'));
      loadStatus();
    } catch (e: any) {
      toast(t('Не сохранено: {e}', { e: e.message }));
    }
    setBusy(null);
  }

  async function act(path: string, done: string) {
    setBusy(path);
    try {
      const st = await send('POST', path);
      st?.state ? setStatus(st) : loadStatus();
      toast(done);
    } catch (e: any) {
      toast(t('Не выполнено: {e}', { e: e.message }));
    }
    setBusy(null);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy('save');
    try {
      const c = await send('PUT', '/automation', form);
      setCfg(c);
      setForm(c);
      setErrs({});
      toast(t('Настройки автоматизации сохранены.'));
      loadStatus();
    } catch (e: any) {
      setErrs(e.fields ?? {});
      toast(t('Настройки не сохранены: {e}', { e: e.message }));
    }
    setBusy(null);
  }

  if (error)
    return (
      <>
        <PageHead title={t('Автоматизация')} />
        <div className="box risk" role="alert">
          {t('Настройки не загружены: {e}', { e: error })}
        </div>
      </>
    );
  if (!cfg || !form)
    return (
      <>
        <PageHead title={t('Автоматизация')} />
        <Skeleton className="h-60" />
      </>
    );

  const st = status?.state;
  const today = status?.today ?? {};
  const budget = (today.cost_usd ?? 0) + (today.budget_left ?? 0) || cfg.evaluate?.daily_budget_usd || 0;
  const used = budget ? Math.min(1, (today.cost_usd ?? 0) / budget) : 0;
  const runningCycle = st === 'syncing' || st === 'evaluating';
  const runWhy = !cfg.enabled ? t('Включите автоматизацию, чтобы запустить цикл.') : st === 'paused' ? t('Продолжите, чтобы запустить цикл.') : runningCycle ? t('Цикл уже идёт.') : '';
  const dirty = JSON.stringify(form) !== JSON.stringify(cfg);
  const last = status?.last_cycle;
  const ev = form.evaluate ?? {};
  const pick = form.sync?.sources;

  return (
    <>
      <PageHead title={t('Автоматизация')} sub={t('Сбор и оценка диалогов по расписанию, без ручного запуска.')} />

      <Card aria-label={t('Состояние')} className="divide-y divide-line2">
        <div className="flex items-start justify-between gap-4 px-4 py-4">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold">{t('Автоматическая обработка')}</h2>
            <p className="text-[13px] text-muted">
              {t('Когда включено, CQA сам забирает новые диалоги из источников и оценивает их по расписанию, в пределах лимитов и бюджета. Когда выключено, всё запускается вручную.')}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={!!cfg.enabled}
            aria-label={t('Автоматизация включена')}
            data-act="automation-toggle"
            disabled={busy === 'toggle'}
            onClick={toggle}
            className={cn('relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors disabled:opacity-45', cfg.enabled ? 'border-accent bg-accent' : 'border-line-strong bg-sunken')}
          >
            <span className={cn('absolute top-0.5 h-[18px] w-[18px] rounded-full bg-surface shadow-card transition-[left] duration-150 ease-out', cfg.enabled ? 'left-[22px]' : 'left-0.5')} />
          </button>
        </div>

        <div className="flex flex-col gap-3 px-4 py-4" data-state={st}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] text-muted">{t('Сейчас')}</span>
              {st ? <Chip tone={STATE[st]?.[1] ?? 'na'}>{STATE[st]?.[0]() ?? st}</Chip> : <Skeleton className="h-5 w-24" />}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {runWhy && <span className="text-xs text-muted">{runWhy}</span>}
              <Button size="sm" data-act="automation-run" disabled={!!runWhy || busy === '/automation/run-now'} onClick={() => act('/automation/run-now', t('Цикл запущен.'))}>
                {t('Запустить сейчас')}
              </Button>
              {st === 'paused' ? (
                <Button size="sm" data-act="automation-resume" disabled={busy === '/automation/resume'} onClick={() => act('/automation/resume', t('Автоматизация продолжена.'))}>
                  {t('Продолжить')}
                </Button>
              ) : (
                <Button size="sm" data-act="automation-pause" disabled={!cfg.enabled || busy === '/automation/pause'} onClick={() => act('/automation/pause', t('Автоматизация на паузе.'))}>
                  {t('Пауза')}
                </Button>
              )}
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] lg:grid-cols-4">
            <div>
              <dt className="text-muted">{t('Следующий цикл')}</dt>
              <dd>{when(status?.next_run_at)}</dd>
            </div>
            <div>
              <dt className="text-muted">{t('Оценено сегодня')}</dt>
              <dd data-today="evaluated">{today.dialogs_evaluated ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-muted">{t('В очереди на оценку')}</dt>
              <dd>{status?.queue_length ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-muted">{t('Бюджет на сегодня')}</dt>
              <dd data-today="budget">{t('{spent} из {budget}', { spent: usd(today.cost_usd), budget: usd(budget) })}</dd>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken" role="meter" aria-label={t('Бюджет на сегодня')} aria-valuemin={0} aria-valuemax={budget} aria-valuenow={today.cost_usd ?? 0}>
                <div className={cn('h-full rounded-full', used >= 1 ? 'bg-risk' : used >= 0.8 ? 'bg-ev' : 'bg-accent')} style={{ width: `${used * 100}%` }} />
              </div>
            </div>
          </dl>
          {last && (
            <p className="text-[13px] text-muted">
              {t('Последний цикл {at}: новых диалогов {n}, оценено {e}, потрачено {cost}.', { at: when(last.started), n: last.new_dialogs ?? 0, e: last.evaluated ?? 0, cost: usd(last.cost) })}
            </p>
          )}
        </div>
      </Card>

      <form onSubmit={save}>
        <Card aria-label={t('Настройки')} className="divide-y divide-line2">
          <Section title={t('Синхронизация')}>
            {chk('sync.enabled', t('Забирать новые диалоги из источников'))}
            {num('sync.every_min', t('Период, мин'), t('Как часто запускать цикл'))}
            {sources.length > 0 && (
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <span className="text-[13px] font-semibold text-ink2">{t('Источники')}</span>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={pick === 'all'} onChange={e => put('sync.sources', e.target.checked ? 'all' : [])} />
                  {t('Все источники')}
                </label>
                {pick !== 'all' &&
                  sources.map(s => (
                    <label key={s.id} className="flex items-center gap-2 pl-6">
                      <input
                        type="checkbox"
                        checked={Array.isArray(pick) && pick.includes(s.id)}
                        onChange={e => put('sync.sources', e.target.checked ? [...(pick ?? []), s.id] : (pick ?? []).filter((x: string) => x !== s.id))}
                      />
                      {s.name}
                    </label>
                  ))}
                {errs['sync.sources'] && <span className="text-xs text-risk">{errs['sync.sources']}</span>}
              </div>
            )}
          </Section>

          <Section title={t('Оценка')}>
            {chk('evaluate.enabled', t('Оценивать диалоги моделью'))}
            {chk('evaluate.on_new_dialogs', t('Оценивать новые диалоги сразу после синхронизации'))}
            {chk('evaluate.only_unscored', t('Только ещё не оценённые'), t('Готовые оценки не пересчитываются и не тратят бюджет'))}
            {'ch' in ev && (
              <Field label={t('Канал')} hint={err('evaluate.ch')}>
                <select className="fld" value={Array.isArray(ev.ch) && ev.ch.length === 1 ? ev.ch[0] : 'all'} onChange={e => put('evaluate.ch', e.target.value === 'all' ? 'all' : [e.target.value])}>
                  <option value="all">{t('Все каналы')}</option>
                  <option value="chat">{t('Только чаты')}</option>
                  <option value="call">{t('Только звонки')}</option>
                </select>
              </Field>
            )}
            {num('evaluate.batch_size', t('Диалогов за цикл'))}
            {num('evaluate.max_per_hour', t('Не больше диалогов в час'))}
            {num('evaluate.daily_budget_usd', t('Бюджет в день, USD'), t('Когда потрачен, оценка ждёт следующего дня по Астане'), '0.01')}
            <Field label={t('Приоритет')} hint={err('evaluate.priority')}>
              <select className="fld" value={ev.priority ?? 'normal'} onChange={e => put('evaluate.priority', e.target.value)}>
                <option value="low">{t('Низкий')}</option>
                <option value="normal">{t('Обычный')}</option>
                <option value="high">{t('Высокий')}</option>
              </select>
            </Field>
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={!!ev.quiet_hours} onChange={e => put('evaluate.quiet_hours', e.target.checked ? { from: '22:00', to: '08:00' } : null)} />
                {t('Тихие часы')}
              </label>
              <span className="text-xs text-muted">{t('В это время модель не вызывается по расписанию; запуск вручную работает')}</span>
              {ev.quiet_hours && (
                <div className="flex flex-wrap gap-3">
                  <Field label={t('С')} hint={err('evaluate.quiet_hours.from')}>
                    <input className="fld" type="time" value={ev.quiet_hours.from ?? ''} onChange={e => put('evaluate.quiet_hours.from', e.target.value)} aria-invalid={!!errs['evaluate.quiet_hours.from']} />
                  </Field>
                  <Field label={t('До')} hint={err('evaluate.quiet_hours.to')}>
                    <input className="fld" type="time" value={ev.quiet_hours.to ?? ''} onChange={e => put('evaluate.quiet_hours.to', e.target.value)} aria-invalid={!!errs['evaluate.quiet_hours.to']} />
                  </Field>
                </div>
              )}
              {errs['evaluate.quiet_hours'] && <span className="text-xs text-risk">{errs['evaluate.quiet_hours']}</span>}
            </div>
          </Section>

          <Section title={t('После оценки')}>
            {chk('after.classify_products', t('Определять продукт'))}
            {chk('after.evaluate_alerts', t('Проверять правила алертов'))}
            {chk('after.prosody_for_calls', t('Считать интонацию по записи звонков'), t('Дольше: нужна запись разговора'))}
          </Section>

          <div className="flex flex-wrap items-center justify-end gap-2.5 px-4 py-3">
            {!dirty && <span className="text-xs text-muted">{t('Изменений нет')}</span>}
            {dirty && (
              <Button variant="ghost" onClick={() => (setForm(cfg), setErrs({}))}>
                {t('Отменить изменения')}
              </Button>
            )}
            <Button type="submit" variant="primary" data-act="automation-save" disabled={!dirty || busy === 'save'} aria-busy={busy === 'save'}>
              {busy === 'save' ? t('Сохраняем…') : t('Сохранить настройки')}
            </Button>
          </div>
        </Card>
      </form>

      <Card aria-label={t('Журнал циклов')}>
        <div className="flex items-center justify-between gap-3 px-4 pb-1.5 pt-4">
          <h2 className="text-base font-semibold">{t('Журнал циклов')}</h2>
          <DownloadButton path="/automation/cycles?format=csv" name="cqa-automation-cycles.csv" kind="automation-cycles-csv" variant="ghost">
            <Download size={16} aria-hidden="true" /> {t('Скачать CSV')}
          </DownloadButton>
        </div>
        {!cycles ? (
          <Skeleton className="m-4 h-24" />
        ) : !cycles.length ? (
          <p className="px-4 pb-4 text-[13px] text-muted">{t('Циклов ещё не было. Первый начнётся после включения или по кнопке «Запустить сейчас».')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>{t('Начало')}</th>
                  <th>{t('Запуск')}</th>
                  <th className="num">{t('Новых диалогов')}</th>
                  <th className="num">{t('Оценено')}</th>
                  <th className="num">{t('Стоимость')}</th>
                  <th>{t('Итог')}</th>
                </tr>
              </thead>
              <tbody>
                {cycles.map(c => (
                  <tr key={c.id ?? c.started}>
                    <td>{when(c.started)}</td>
                    <td>{c.trigger === 'manual' ? t('вручную') : t('по расписанию')}</td>
                    <td className="num">{c.new_dialogs ?? 0}</td>
                    <td className="num">{c.evaluated ?? 0}</td>
                    <td className="num">{usd(c.cost)}</td>
                    <td className="text-[13px]">
                      {c.errors?.length ? (
                        <Tip content={c.errors.slice(0, 5).join('; ')}>
                          <span className="text-risk" tabIndex={0}>
                            {t('ошибок: {n}', { n: c.errors.length })}
                          </span>
                        </Tip>
                      ) : c.skipped ? (
                        <span className="text-ev">{t('оценка пропущена: {why}', { why: SKIP[c.skipped]?.() ?? c.skipped })}</span>
                      ) : c.finished ? (
                        t('успешно')
                      ) : (
                        t('идёт')
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
