// Экран «Алерты»: GET /api/alerts с фильтрами статуса и важности, «Принять», «Решить» с заметкой, «Назначить»,
// «Почему» (basis сервера как есть, без догадок интерфейса) и переход к объекту. Формы — helpers-ops.md, «Алерты и маркеры».
import { ChevronDown, ChevronUp, RefreshCw, SlidersHorizontal, X } from 'lucide-react';
import { Fragment, useEffect, useState } from 'react';
import { titleOf } from '../lib/format.js';
import { lang, t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { api, toast } from '../lib/state.js';
import { refreshOps } from '../ops';
import { go, useRoute, useS } from '../store';
import { Button, Card, Chip, cn, Field, Modal, PageHead, Skeleton, Tip, type Tone } from '../ui';
import { RulesDialog } from './alerts/Rules';

// Подписи — функции: t() при отрисовке, после смены языка.
const SEV: Record<string, [() => string, Tone, number]> = {
  critical: [() => t('Критичный'), 'risk', 0],
  warning: [() => t('Предупреждение'), 'ev', 1],
  info: [() => t('Сведения'), 'info', 2],
};
const STATUS: Record<string, [() => string, Tone, number]> = {
  new: [() => t('Новый'), 'ev', 0],
  ack: [() => t('Принят'), 'info', 1],
  resolved: [() => t('Решён'), 'ok', 2],
};
const TARGET: Record<string, () => string> = {
  dialog: () => t('Диалог'),
  operator: () => t('Оператор'),
  run: () => t('Прогон'),
  set: () => t('Набор'),
};
// Подписи полей basis; поле без подписи показывается под своим именем.
const BASIS: Record<string, () => string> = {
  rule: () => t('Правило'),
  metric: () => t('Показатель'),
  threshold: () => t('Порог'),
  value: () => t('Наблюдённое значение'),
  observed: () => t('Наблюдённое значение'),
  window: () => t('Период'),
  dialogs: () => t('Диалоги'),
  lines: () => t('Реплики'),
  criteria: () => t('Критерии'),
  appeals: () => t('Апелляции'),
};
const LOCALE: Record<string, string> = { ru: 'ru-RU', en: 'en-GB', kk: 'kk-KZ' };

// Черновики заметок «Решить» по id алерта: живут, пока открыта вкладка, и переживают переход между экранами.
const drafts: Record<string, string> = {};

/** Ответ GET /api/alerts: {alerts, counts} (design/contract.md); массив и {items} — от заглушек. */
const itemsOf = (data: any): any[] => (Array.isArray(data) ? data : (data?.alerts ?? data?.items ?? []));

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString(LOCALE[lang] ?? 'ru-RU', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—';

function targetOf(a: any, dialogs: any[]): { to: string; label: string } {
  const kind = TARGET[a.target_type]?.() ?? a.target_type;
  if (a.target_type === 'dialog') {
    const d = dialogs.find(x => x.id === a.target_id);
    return { to: href('d', a.target_id), label: d ? titleOf(d) : `${kind} ${a.target_id}` }; // «Чат sc-26» уже говорит, что это диалог
  }
  if (a.target_type === 'operator') return { to: href('people', a.target_id), label: `${kind} ${a.target_id}` };
  if (a.target_type === 'run') return { to: href('analytics'), label: `${kind} ${a.target_id}` };
  return { to: href('queue'), label: a.target_id ? `${kind} ${a.target_id}` : kind };
}

const plain = (v: any) => (v == null ? '—' : typeof v === 'object' ? (Array.isArray(v) && v.every(x => typeof x !== 'object') ? v.join(', ') : JSON.stringify(v)) : String(v));

/** «Почему»: поля basis сервера; реплики и диалоги — ссылками в карточку. */
export function Basis({ basis, dialog }: { basis: any; dialog?: string | null }) {
  if (typeof basis !== 'object' || basis == null) return <p className="text-[13px]">{plain(basis)}</p>;
  const lines = (v: any[]) =>
    v.map((x, i) => {
      const n = typeof x === 'object' ? x.n : x;
      const dlg = (typeof x === 'object' && x.dlg) || basis.dialog || dialog;
      return (
        <span key={i} className="block">
          {dlg ? <a href={href('d', dlg, { n: String(n) })}>{t('Реплика {n}', { n })}</a> : t('Реплика {n}', { n })}
          {typeof x === 'object' && x.text && <span className="text-ink2">: «{x.text}»</span>}
        </span>
      );
    });
  return (
    <div className="flex flex-col gap-2">
      {basis.why && <p className="text-[13px]">{basis.why}</p>}
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13px]">
        {Object.entries(basis)
          .filter(([k, v]) => v != null && v !== '' && k !== 'dialog' && k !== 'why')
          .map(([k, v]) => (
            <Fragment key={k}>
              <dt className="text-muted">{BASIS[k]?.() ?? k}</dt>
              <dd className="[overflow-wrap:anywhere]">
                {k === 'lines' && Array.isArray(v)
                  ? lines(v)
                  : k === 'dialogs' && Array.isArray(v)
                    ? v.map((id: string, i: number) => (
                        <Fragment key={id}>
                          {i > 0 && ', '}
                          <a href={href('d', id)}>{id}</a>
                        </Fragment>
                      ))
                    : plain(v)}
              </dd>
            </Fragment>
          ))}
      </dl>
    </div>
  );
}

function ResolveDialog({ a, onClose, onDone }: { a: any; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState(drafts[a.id] ?? '');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!note.trim()) return setErr(t('Напишите, что сделано: заметка останется в журнале действий.'));
    setBusy(true);
    try {
      await api.post(`/alerts/${encodeURIComponent(a.id)}/resolve`, { note: note.trim() });
      delete drafts[a.id];
      toast(t('Алерт решён.'));
      onDone();
    } catch (e: any) {
      toast(t('Алерт не решён: {e}', { e: e.message }));
      setBusy(false);
    }
  }
  return (
    <Modal open onOpenChange={v => !v && onClose()} title={t('Решить алерт')} description={a.title}>
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        <Field label={t('Заметка')} hint={t('Что проверили и что сделали. Черновик сохранится, если закрыть окно.')}>
          <textarea
            className="fld min-h-24"
            value={note}
            autoFocus
            aria-invalid={!!err}
            onChange={e => {
              setNote(e.target.value);
              drafts[a.id] = e.target.value;
              if (err) setErr('');
            }}
          />
        </Field>
        {err && <p className="text-[13px] text-risk">{err}</p>}
        <div className="flex justify-end gap-2.5">
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button type="submit" variant="primary" data-act="resolve-save" disabled={busy}>
            {busy ? t('Сохраняем…') : t('Решить')}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function Alerts({ id }: { id: string | null }) {
  const S = useS();
  const { params: p } = useRoute();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState<string | null>(id);
  const [busy, setBusy] = useState<string | null>(null);
  const [resolving, setResolving] = useState<any>(null);
  const [rules, setRules] = useState(false);
  const [checking, setChecking] = useState(false);
  const canAct = S.role !== 'operator';
  const status = p.status || '',
    sev = p.severity || '';

  async function load() {
    try {
      const q = new URLSearchParams(Object.entries({ status, severity: sev }).filter(([, v]) => v)).toString();
      setData(await api.get(`/alerts${q ? '?' + q : ''}`));
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }
  useEffect(() => {
    load();
  }, [status, sev]);
  useEffect(() => {
    if (id) setOpen(id);
  }, [id]);

  async function act(a: any, f: () => Promise<unknown>, done: string, fail: string) {
    setBusy(a.id);
    try {
      await f();
      toast(done);
      await load();
      refreshOps();
    } catch (e: any) {
      toast(`${fail}: ${e.message}`); // fail уже переведён
    } finally {
      setBusy(null);
    }
  }

  async function evaluate() {
    setChecking(true);
    try {
      const r: any = await api.post('/alerts/evaluate');
      const n = r?.created?.length ?? 0;
      toast(n ? t('Правила проверены, новых алертов: {n}.', { n }) : t('Правила проверены, новых алертов нет.'));
      await load();
      refreshOps();
    } catch (e: any) {
      toast(t('Проверка не выполнена: {e}', { e: e.message }));
    } finally {
      setChecking(false);
    }
  }

  const setParam = (k: string, v: string) => go(href('alerts', id, { ...p, [k]: v }));
  const sel = (label: string, k: string, value: string, vals: [string, string][]) => (
    <label className="flex items-center gap-2 text-[13px] text-muted">
      {label}
      <select className="fld" data-act={`f-${k}`} value={value} onChange={e => setParam(k, e.target.value)}>
        {vals.map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
    </label>
  );

  const items = itemsOf(data)
    .slice()
    .sort((a, b) => (STATUS[a.status]?.[2] ?? 3) - (STATUS[b.status]?.[2] ?? 3) || (SEV[a.severity]?.[2] ?? 3) - (SEV[b.severity]?.[2] ?? 3) || String(b.created).localeCompare(String(a.created)));
  const counts = data?.counts ?? (!status ? Object.fromEntries(Object.keys(STATUS).map(k => [k, items.filter(a => a.status === k).length])) : null);
  const employees: any[] = S.employees ?? [];
  const nameOf = (eid: string | null) => (eid ? (employees.find(x => x.id === eid)?.name ?? eid) : null);

  return (
    <>
      <PageHead title={t('Алерты')} sub={t('Сигналы правил по диалогам, сотрудникам и прогонам. Примите алерт, чтобы взять его в работу, и решите с заметкой.')}>
        {canAct && (
          <>
            <Button data-act="rules" onClick={() => setRules(true)}>
              <SlidersHorizontal size={16} aria-hidden="true" /> {t('Правила алертов')}
            </Button>
            <Tip content={t('Проверить все включённые правила на текущих данных. Само это происходит после оценки, апелляции и решения.')}>
              <Button data-act="evaluate" disabled={checking} onClick={evaluate}>
                <RefreshCw size={16} aria-hidden="true" /> {checking ? t('Проверяем…') : t('Проверить сейчас')}
              </Button>
            </Tip>
          </>
        )}
      </PageHead>
      {rules && <RulesDialog onClose={() => setRules(false)} />}
      {counts && (
        <p className="text-ink2">
          <b className="text-ink">{t('Новых: {n}', { n: counts.new ?? 0 })}</b>
          {t(', принятых: {a}, решённых: {r}.', { a: counts.ack ?? 0, r: counts.resolved ?? 0 })}
        </p>
      )}
      <Card aria-label={t('Список алертов')}>
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-3.5 py-3">
          {sel(t('Статус'), 'status', status, [
            ['', t('Все')],
            ['new', t('Новые')],
            ['ack', t('Принятые')],
            ['resolved', t('Решённые')],
          ])}
          {sel(t('Важность'), 'severity', sev, [
            ['', t('Все')],
            ['critical', t('Критичные')],
            ['warning', t('Предупреждения')],
            ['info', t('Сведения')],
          ])}
          {(status || sev) && (
            <Button size="sm" data-act="clear" onClick={() => go(href('alerts', id))}>
              <X size={16} aria-hidden="true" /> {t('Сбросить фильтры')}
            </Button>
          )}
        </div>
        {error ? (
          <div className="flex flex-col items-start gap-3 p-5">
            <p className="text-risk">{t('Алерты не загрузились: {e}', { e: error })}</p>
            <Button onClick={load}>{t('Повторить')}</Button>
          </div>
        ) : data == null ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : !items.length ? (
          <div className="flex flex-col items-start gap-3 p-5">
            {status || sev ? (
              <>
                <p className="text-muted">{t('Под эти фильтры алертов нет.')}</p>
                <Button onClick={() => go(href('alerts', id))}>{t('Сбросить фильтры')}</Button>
              </>
            ) : (
              <>
                <p className="text-muted">{t('Алертов нет: правила не нашли ничего, что требует внимания.')}</p>
                <Button onClick={() => go(href('queue'))}>{t('Перейти к диалогам')}</Button>
              </>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl md:min-w-[920px]">
              <thead>
                <tr>
                  <th>{t('Важность')}</th>
                  <th>{t('Алерт')}</th>
                  <th>{t('Объект')}</th>
                  <th className="hidden md:table-cell">{t('Создан')}</th>
                  <th>{t('Статус')}</th>
                  <th className="hidden md:table-cell">{t('Ответственный')}</th>
                  <th className="!text-right">{t('Действия')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map(a => {
                  const [sl, st] = SEV[a.severity] ?? [() => a.severity, 'na'];
                  const [stl, stt] = STATUS[a.status] ?? [() => a.status, 'na'];
                  const to = targetOf(a, S.dialogs);
                  const shown = open === String(a.id);
                  const off = busy === a.id;
                  return (
                    <Fragment key={a.id}>
                      <tr className={cn('align-top', shown && 'sel')} data-alert={a.id}>
                        <td>
                          <Chip tone={st}>{sl()}</Chip>
                        </td>
                        <td>
                          <span className="font-semibold">{a.title}</span>
                          {(a.basis != null || a.note) && (
                            <button
                              type="button"
                              className="mt-0.5 flex items-center gap-1 text-[13px] font-semibold text-accent hover:text-accent-ink"
                              data-act="why"
                              aria-expanded={shown}
                              onClick={() => setOpen(shown ? null : String(a.id))}
                            >
                              {t('Почему')} {shown ? <ChevronUp size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
                            </button>
                          )}
                        </td>
                        <td className="whitespace-nowrap">
                          <a href={to.to} data-act="target">
                            {to.label}
                          </a>
                        </td>
                        <td className="hidden whitespace-nowrap text-[13px] text-muted md:table-cell">{when(a.created)}</td>
                        <td>
                          <Chip tone={stt}>{stl()}</Chip>
                          {a.status === 'resolved' && (a.resolved_by || a.resolved_at) && (
                            <span className="mt-1 block text-xs text-muted">
                              {nameOf(a.resolved_by) ?? ''} {when(a.resolved_at)}
                            </span>
                          )}
                        </td>
                        <td className="hidden md:table-cell">
                          {canAct && employees.length > 0 && a.status !== 'resolved' ? (
                            <select
                              className="fld min-h-8 text-[13px]"
                              aria-label={t('Назначить')}
                              data-act="assign"
                              disabled={off}
                              value={a.assignee ?? ''}
                              onChange={e => {
                                const v = e.target.value || null;
                                act(
                                  a,
                                  () => api.put(`/alerts/${encodeURIComponent(a.id)}/assignee`, { assignee: v }),
                                  v ? t('Назначен: {name}.', { name: nameOf(v) }) : t('Назначение снято.'),
                                  t('Не назначено'),
                                );
                              }}
                            >
                              <option value="">{t('Не назначен')}</option>
                              {employees
                                .filter(x => x.active !== false || x.id === a.assignee)
                                .map(x => (
                                  <option key={x.id} value={x.id}>
                                    {x.name}
                                  </option>
                                ))}
                            </select>
                          ) : (
                            <span className={a.assignee ? '' : 'text-muted'}>{nameOf(a.assignee) ?? '—'}</span>
                          )}
                        </td>
                        <td>
                          <div className="flex flex-wrap justify-end gap-1.5 md:flex-nowrap">
                            {canAct && a.status === 'new' && (
                              <Button
                                size="sm"
                                data-act="ack"
                                disabled={off}
                                onClick={() => act(a, () => api.post(`/alerts/${encodeURIComponent(a.id)}/ack`), t('Алерт принят в работу.'), t('Алерт не принят'))}
                              >
                                {t('Принять')}
                              </Button>
                            )}
                            {canAct && a.status !== 'resolved' && (
                              <Button size="sm" data-act="resolve" disabled={off} onClick={() => setResolving(a)}>
                                {t('Решить')}
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {shown && (
                        <tr className="bg-sunken">
                          <td colSpan={7}>
                            <div className="flex flex-col gap-3 py-1" role="region" aria-label={t('Почему')}>
                              {a.basis != null ? (
                                <Basis basis={a.basis} dialog={a.target_type === 'dialog' ? a.target_id : null} />
                              ) : (
                                <p className="text-[13px] text-muted">{t('Сервер не прислал обоснование для этого алерта.')}</p>
                              )}
                              {a.rule_id && <span className="text-xs text-muted">{t('Правило алерта: {id}', { id: a.rule_id })}</span>}
                              {a.note && (
                                <p className="text-[13px]">
                                  <span className="text-muted">{t('Заметка:')} </span>
                                  {a.note}
                                </p>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {resolving && (
        <ResolveDialog
          a={resolving}
          onClose={() => setResolving(null)}
          onDone={async () => {
            setResolving(null);
            await load();
            refreshOps();
          }}
        />
      )}
    </>
  );
}
