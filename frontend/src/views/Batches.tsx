// Экран «Пакеты»: большие объёмы оцениваются заданиями, задание делится на батчи (design/contract.md,
// «Пакетная обработка»). Список заданий с прогрессом, страница задания с батчами и действиями,
// окно «Новый пакет» по фильтрам или списком диалогов. Опрос раз в 3 с, пока есть задания в работе.
import { ArrowLeft, ChevronDown, ChevronUp, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { f2, loc, titleOf } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { api, toast } from '../lib/state.js';
import { go, useRoute, useS } from '../store';
import { Button, Card, Chip, Field, Modal, PageHead, Skeleton, Tip, type Tone } from '../ui';

// Подписи — функции: t() при отрисовке, после смены языка.
const STATUS: Record<string, [() => string, Tone]> = {
  queued: [() => t('В очереди'), 'info'],
  running: [() => t('Идёт'), 'info'],
  paused: [() => t('На паузе'), 'ev'],
  done: [() => t('Готово'), 'ok'],
  cancelled: [() => t('Отменён'), 'na'],
  failed: [() => t('Ошибка'), 'risk'],
};
const PRIORITY: Record<string, () => string> = { high: () => t('Высокий'), normal: () => t('Обычный'), low: () => t('Низкий') };
const ACTIVE = ['queued', 'running'];

const jobsOf = (data: any): any[] => (Array.isArray(data) ? data : (data?.jobs ?? []));
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(loc(), { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—');
const usd = (x: number | null | undefined) => (x == null ? '—' : `$${f2(x)}`);

function eta(s: number | null | undefined) {
  if (s == null) return '—';
  if (s < 60) return t('{n} с', { n: Math.round(s) });
  if (s < 3600) return t('{n} мин', { n: Math.round(s / 60) });
  return t('{h} ч {m} мин', { h: Math.floor(s / 3600), m: Math.round((s % 3600) / 60) });
}
const speed = (x: number | null | undefined) => (x == null ? '—' : t('{n} диал./мин', { n: f2(x) }));
const limitText = (rl: any) =>
  !rl ? '' : rl.rpm ? t('Лимит модели: {rpm} запросов в минуту, до {parallel} одновременно.', rl) : t('Лимит модели: без лимита запросов, до {parallel} одновременно.', rl);

/** Полоса прогресса: оценено (accent) и с ошибкой (risk) от всего задания. */
function Progress({ j }: { j: any }) {
  const total = j.total || 0;
  const pct = (n: number) => (total ? Math.min(100, (n / total) * 100) : 0);
  return (
    <div className="flex min-w-[140px] flex-col gap-1">
      <div className="flex h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={j.done} aria-label={t('Прогресс пакета')}>
        <div className="bg-accent transition-[width] duration-200 ease-out" style={{ width: `${pct(j.done - (j.errors || 0))}%` }} />
        <div className="bg-risk transition-[width] duration-200 ease-out" style={{ width: `${pct(j.errors || 0)}%` }} />
      </div>
      <span className="text-xs text-muted">
        {t('{done} из {total} диалогов', { done: j.done, total })}
        {j.errors > 0 && <span className="text-risk"> · {t('ошибок: {n}', { n: j.errors })}</span>}
      </span>
    </div>
  );
}

function StatusChip({ s }: { s: string }) {
  const [label, tone] = STATUS[s] ?? [() => s, 'na' as Tone];
  return (
    <Chip tone={tone} data-status={s}>
      {label()}
    </Chip>
  );
}

/** Окно «Новый пакет»: по фильтрам (поля Dialog) или списком id. Фильтры можно передать адресом #/batches?new=1&ch=&lang=&prod=. */
function NewBatch({ onClose }: { onClose: () => void }) {
  const S = useS();
  const { params: p } = useRoute();
  const dialogs: any[] = S.dialogs ?? [];
  const uniq = (f: (d: any) => string | undefined) => [...new Set(dialogs.map(f).filter(Boolean) as string[])].sort();
  const langs = uniq(d => d.lang),
    products = uniq(d => d.product?.id),
    sources = uniq(d => d.source_id);
  const [by, setBy] = useState<'filter' | 'list'>(p.ids ? 'list' : 'filter');
  const [f, setF] = useState({ ch: p.ch ?? '', lang: p.lang ?? '', product: p.prod ?? '', source_id: p.src ?? '', since: '', unscored_only: true });
  const [ids, setIds] = useState(p.ids ?? '');
  const [size, setSize] = useState('20');
  const [priority, setPriority] = useState('normal');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const setFld = (k: string, v: any) => setF({ ...f, [k]: v });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const out: Record<string, string> = {};
    const list = ids.split(/[\s,;]+/).filter(Boolean);
    if (by === 'list') {
      const known = new Set(dialogs.map(d => d.id));
      const unknown = list.filter(x => !known.has(x));
      if (!list.length) out.ids = t('Укажите хотя бы один диалог.');
      else if (unknown.length) out.ids = t('Таких диалогов нет: {ids}', { ids: unknown.join(', ') });
    }
    const n = Number(size);
    if (!Number.isInteger(n) || n < 1 || n > 200) out.size = t('Размер батча: целое число от 1 до 200.');
    setErrs(out);
    if (Object.keys(out).length) return;
    const filter = Object.fromEntries(Object.entries(f).filter(([k, v]) => v !== '' || k === 'unscored_only'));
    setBusy(true);
    try {
      const job = await api.post('/batches', { ...(by === 'list' ? { dialogs: list } : { filter }), batch_size: n, priority });
      toast(t('Пакет создан: {n} диалогов в очереди.', { n: job.total ?? 0 }));
      go(href('batches', String(job.id)));
      onClose();
    } catch (e: any) {
      setErrs({ form: t('Пакет не создан: {e}', { e: e.message }) });
      setBusy(false);
    }
  }

  const sel = (label: string, k: string, vals: [string, string][]) => (
    <Field label={label}>
      <select className="fld" value={(f as any)[k]} onChange={e => setFld(k, e.target.value)}>
        {vals.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </Field>
  );
  const all = (vs: string[]): [string, string][] => [['', t('Все')], ...vs.map(v => [v, v] as [string, string])];

  return (
    <Modal open onOpenChange={v => !v && onClose()} title={t('Новый пакет')} description={t('Диалоги делятся на батчи и оцениваются по очереди. Следующий батч берётся у пакета с высшим приоритетом.')}>
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        <fieldset className="flex flex-wrap gap-4 text-sm">
          <legend className="mb-1.5 text-[13px] font-semibold text-ink2">{t('Что оценить')}</legend>
          <label className="flex items-center gap-2">
            <input type="radio" name="by" checked={by === 'filter'} onChange={() => setBy('filter')} />
            {t('По фильтрам')}
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="by" checked={by === 'list'} onChange={() => setBy('list')} />
            {t('Списком диалогов')}
          </label>
        </fieldset>
        {by === 'filter' ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {sel(t('Канал'), 'ch', [
              ['', t('Все')],
              ['chat', t('Чат')],
              ['call', t('Звонок')],
            ])}
            {sel(t('Язык'), 'lang', all(langs))}
            {products.length > 0 && sel(t('Продукт'), 'product', all(products))}
            {sources.length > 0 && sel(t('Источник'), 'source_id', all(sources))}
            <Field label={t('С даты')} hint={t('Диалоги не раньше этой даты.')}>
              <input type="date" className="fld" value={f.since} onChange={e => setFld('since', e.target.value)} />
            </Field>
            <label className="flex items-center gap-2 self-center text-sm sm:col-span-2">
              <input type="checkbox" checked={f.unscored_only} onChange={e => setFld('unscored_only', e.target.checked)} />
              {t('Только неоценённые')}
              <span className="text-xs text-muted">{t('Диалоги, у которых есть критерии без оценки.')}</span>
            </label>
          </div>
        ) : (
          <Field label={t('Диалоги')} hint={t('Id по одному в строке или через запятую.')}>
            <textarea className="fld min-h-24" value={ids} aria-invalid={!!errs.ids} onChange={e => setIds(e.target.value)} placeholder={dialogs[0]?.id ?? ''} />
          </Field>
        )}
        {errs.ids && <p className="text-[13px] text-risk">{errs.ids}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('Размер батча')} hint={t('Диалогов в одном запуске, от 1 до 200.')}>
            <input type="number" min={1} max={200} className="fld" value={size} aria-invalid={!!errs.size} onChange={e => setSize(e.target.value)} />
          </Field>
          <Field label={t('Приоритет')}>
            <select className="fld" value={priority} onChange={e => setPriority(e.target.value)}>
              {Object.entries(PRIORITY).map(([v, l]) => (
                <option key={v} value={v}>
                  {l()}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {errs.size && <p className="text-[13px] text-risk">{errs.size}</p>}
        {errs.form && <p className="text-[13px] text-risk">{errs.form}</p>}
        <div className="flex justify-end gap-2.5">
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button type="submit" variant="primary" data-act="batch-create" disabled={busy}>
            {busy ? t('Создаём…') : t('Создать пакет')}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** Действие задания и причина, почему оно недоступно (null — доступно). Правила — design/contract.md. */
const ACTIONS: [string, () => string, (j: any) => string | null][] = [
  ['pause', () => t('Пауза'), j => (ACTIVE.includes(j.status) ? null : t('Только для пакета в очереди или в работе.'))],
  ['resume', () => t('Продолжить'), j => (j.status === 'paused' ? null : t('Только для пакета на паузе.'))],
  ['cancel', () => t('Отменить'), j => (['queued', 'running', 'paused'].includes(j.status) ? null : t('Пакет уже закончен.'))],
  ['retry', () => t('Повторить ошибки'), j => (j.status === 'cancelled' ? t('Отменённый пакет не повторяется.') : !j.errors ? t('Нет диалогов с ошибкой.') : null)],
];

function Job({ id }: { id: string }) {
  const S = useS();
  const [j, setJ] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [why, setWhy] = useState(false);
  const load = async () => {
    try {
      setJ(await api.get(`/batches/${encodeURIComponent(id)}`));
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  };
  useEffect(() => {
    load();
  }, [id]);
  useEffect(() => {
    if (!j || !ACTIVE.includes(j.status)) return;
    const h = setTimeout(load, 3000);
    return () => clearTimeout(h);
  }, [j]);

  async function act(a: string) {
    if (a === 'cancel' && !confirm(t('Отменить пакет? Текущий батч доработает, остальные диалоги не будут оценены.'))) return;
    setBusy(true);
    try {
      setJ(await api.post(`/batches/${encodeURIComponent(id)}/${a}`));
      toast(t('Готово: {action}.', { action: ACTIONS.find(x => x[0] === a)![1]() }));
    } catch (e: any) {
      toast(t('Действие не выполнено: {e}', { e: e.message }));
    } finally {
      setBusy(false);
    }
  }

  const back = (
    <a href={href('batches')} className="inline-flex items-center gap-1.5 text-[13px]">
      <ArrowLeft size={16} aria-hidden="true" /> {t('Все пакеты')}
    </a>
  );
  if (error)
    return (
      <>
        {back}
        <PageHead title={t('Пакет {id}', { id })} />
        <p className="text-risk">{t('Пакет не загрузился: {e}', { e: error })}</p>
        <Button onClick={load}>{t('Повторить')}</Button>
      </>
    );
  if (!j)
    return (
      <>
        {back}
        <PageHead title={t('Пакет {id}', { id })} />
        <Skeleton className="h-32" />
      </>
    );
  const titleOfDialog = (did: string) => {
    const d = (S.dialogs ?? []).find((x: any) => x.id === did);
    return d ? titleOf(d) : did;
  };
  return (
    <>
      {back}
      <PageHead
        title={
          <span className="flex items-center gap-3">
            {t('Пакет {id}', { id: j.id })} <StatusChip s={j.status} />
          </span>
        }
        sub={t('Создан {at} · приоритет {p} · по {n} диалогов в батче', { at: when(j.created), p: PRIORITY[j.priority]?.() ?? j.priority, n: j.batch_size })}
      />
      {j.note && <p className="box ev">{j.note}</p>}
      <Card className="divide-y divide-line2">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3 px-4 py-3.5">
          <Progress j={j} />
          <div>
            <div className="text-xs text-muted">{t('Скорость')}</div>
            <div className="num">{speed(j.throughput_per_min)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">{t('Осталось')}</div>
            <div className="flex items-center gap-1.5">
              <span className="num">{ACTIVE.includes(j.status) ? eta(j.eta_s) : '—'}</span>
              <Button size="sm" variant="ghost" data-act="eta-why" aria-expanded={why} onClick={() => setWhy(!why)}>
                {t('Почему')} {why ? <ChevronUp size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />}
              </Button>
            </div>
          </div>
          <div>
            <div className="text-xs text-muted">{t('Стоимость')}</div>
            <div className="num">{usd(j.cost)}</div>
          </div>
        </div>
        {why && (
          <div className="px-4 py-3 text-[13px]" role="region" aria-label={t('Почему')}>
            <p>{j.eta_basis ? t('Оценка времени: {basis}.', { basis: j.eta_basis }) : t('Сервер не прислал основание оценки времени.')}</p>
            <p className="text-muted">{limitText(j.rate_limit)}</p>
          </div>
        )}
        <div className="flex flex-wrap items-start gap-4 px-4 py-3.5">
          {ACTIONS.map(([a, label, off]) => {
            const reason = off(j);
            return (
              <div key={a} className="flex max-w-[220px] flex-col gap-1">
                <Button size="sm" variant={a === 'cancel' ? 'danger' : 'default'} data-act={`batch-${a}`} disabled={busy || !!reason} onClick={() => act(a)}>
                  {label()}
                </Button>
                {reason && <span className="text-xs text-muted">{reason}</span>}
              </div>
            );
          })}
        </div>
        <p className="px-4 py-2.5 text-xs text-muted">{t('Пауза и отмена не прерывают батч в работе: он доработает, следующий не начнётся.')}</p>
      </Card>
      <Card aria-label={t('Батчи')}>
        <h2 className="border-b border-line px-4 py-3 text-[15px] font-semibold">{t('Батчи')}</h2>
        {!j.batches?.length ? (
          <p className="px-4 py-4 text-muted">{t('Батчей ещё нет: пакет ждёт своей очереди.')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl" data-act="batches-table">
              <thead>
                <tr>
                  <th>№</th>
                  <th className="!text-right">{t('Диалогов')}</th>
                  <th className="!text-right">{t('Готово')}</th>
                  <th className="!text-right">{t('Ошибок')}</th>
                  <th>{t('Начат')}</th>
                  <th>{t('Закончен')}</th>
                  <th className="!text-right">{t('Стоимость')}</th>
                </tr>
              </thead>
              <tbody>
                {j.batches.map((b: any) => (
                  <tr key={b.no} data-batch={b.no}>
                    <td>{b.no}</td>
                    <td className="num text-right">{b.n}</td>
                    <td className="num text-right">{b.done}</td>
                    <td className={b.errors ? 'num text-right text-risk' : 'num text-right'}>{b.errors}</td>
                    <td className="whitespace-nowrap text-[13px] text-muted">{when(b.started)}</td>
                    <td className="whitespace-nowrap text-[13px] text-muted">{when(b.finished)}</td>
                    <td className="num text-right">{usd(b.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {j.failed?.length > 0 && (
        <Card aria-label={t('Диалоги с ошибкой')}>
          <h2 className="border-b border-line px-4 py-3 text-[15px] font-semibold">{t('Диалоги с ошибкой')}</h2>
          <ul className="divide-y divide-line2">
            {j.failed.map((x: any) => (
              <li key={x.dialog} className="flex flex-wrap gap-x-3 px-4 py-2.5 text-[13px]">
                <a href={href('d', x.dialog)}>{titleOfDialog(x.dialog)}</a>
                <span className="text-ink2 [overflow-wrap:anywhere]">{x.error}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

export function Batches({ id }: { id: string | null }) {
  const S = useS();
  const { params: p } = useRoute();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(!!p.new);
  const canRun = S.role === 'qa';
  const load = async () => {
    try {
      setData(await api.get('/batches'));
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  };
  const jobs = jobsOf(data);
  useEffect(() => {
    if (!id) load();
  }, [id]);
  useEffect(() => {
    if (id || !jobs.some(j => ACTIVE.includes(j.status))) return;
    const h = setTimeout(load, 3000);
    return () => clearTimeout(h);
  }, [data, id]);

  if (id) return <Job id={id} />;
  const create = canRun && (
    <Button variant="primary" data-act="batch-new" onClick={() => setCreating(true)}>
      <Plus size={16} aria-hidden="true" /> {t('Новый пакет')}
    </Button>
  );
  return (
    <>
      <PageHead title={t('Пакеты')} sub={t('Оценка больших объёмов по частям: прогресс, скорость и оставшееся время по каждому пакету.')}>
        {create}
      </PageHead>
      {data?.rate_limit && <p className="text-[13px] text-muted">{limitText(data.rate_limit)}</p>}
      <Card aria-label={t('Список пакетов')}>
        {error ? (
          <div className="flex flex-col items-start gap-3 p-5">
            <p className="text-risk">{t('Пакеты не загрузились: {e}', { e: error })}</p>
            <Button onClick={load}>{t('Повторить')}</Button>
          </div>
        ) : data == null ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : !jobs.length ? (
          <div className="flex flex-col items-start gap-3 p-5">
            <p className="text-muted">{t('Пакетов пока нет.')}</p>
            {canRun && <p className="text-[13px] text-muted">{t('Создайте первый кнопкой «Новый пакет»: можно взять диалоги по фильтрам очереди или списком.')}</p>}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl md:min-w-[860px]">
              <thead>
                <tr>
                  <th>{t('Пакет')}</th>
                  <th>{t('Статус')}</th>
                  <th>{t('Прогресс')}</th>
                  <th className="!text-right">{t('Скорость')}</th>
                  <th className="!text-right">{t('Осталось')}</th>
                  <th className="!text-right">{t('Стоимость')}</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(j => (
                  <tr key={j.id} className="click" data-job={j.id} onClick={() => go(href('batches', String(j.id)))}>
                    <td>
                      <a href={href('batches', String(j.id))} className="font-semibold" onClick={e => e.stopPropagation()}>
                        {t('Пакет {id}', { id: j.id })}
                      </a>
                      <span className="block text-xs text-muted">
                        {when(j.created)} · {PRIORITY[j.priority]?.() ?? j.priority}
                      </span>
                    </td>
                    <td>
                      <StatusChip s={j.status} />
                      {j.note && <span className="mt-1 block max-w-[220px] text-xs text-muted">{j.note}</span>}
                    </td>
                    <td>
                      <Progress j={j} />
                    </td>
                    <td className="num whitespace-nowrap text-right">{speed(j.throughput_per_min)}</td>
                    <td className="whitespace-nowrap text-right">
                      {ACTIVE.includes(j.status) && j.eta_basis ? (
                        <Tip content={t('Почему: {basis}', { basis: j.eta_basis })}>
                          <span tabIndex={0} className="num underline decoration-line-strong decoration-dotted underline-offset-[3px]">
                            {eta(j.eta_s)}
                          </span>
                        </Tip>
                      ) : (
                        <span className="num">{ACTIVE.includes(j.status) ? eta(j.eta_s) : '—'}</span>
                      )}
                    </td>
                    <td className="num text-right">{usd(j.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && <NewBatch onClose={() => (setCreating(false), load())} />}
    </>
  );
}
