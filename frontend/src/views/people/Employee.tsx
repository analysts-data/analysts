// Страница сотрудника #/people/<id>: оценки его диалогов (GET /api/operators/{name}: итог с n и разбросом, грубые ошибки,
// слабые критерии, тренд по дням), действия из журнала (GET /api/overview), правка карточки (PUT /api/employees/{id}).
// id — сотрудник справочника или имя оператора из диалогов, которого в справочнике нет.
import { ArrowLeft, History, Pencil } from 'lucide-react';
import { lazy, Suspense, useState } from 'react';
import { f2, fn, titleOf } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { href } from '../../lib/router.js';
import { calc } from '../../lib/scoring.js';
import { api, toast } from '../../lib/state.js';
import { refreshOps } from '../../ops';
import { useS } from '../../store';
import { Term } from '../../terms';
import { Button, Card, Chip, Field, LinkButton, Modal, PageHead, Skeleton, Tip } from '../../ui';
import { actionName, listOf, pct, roleName, roleNames, useGet } from './net';

// ECharts — отдельный кусок сборки, как у «Аналитики»: грузится, только когда есть тренд.
const Chart = lazy(() => import('../analytics/Chart').then(m => ({ default: m.Chart })));

function Stat({ value, to, children }: { value: React.ReactNode; to?: string; children: React.ReactNode }) {
  const body = (
    <>
      <strong className="block text-[28px] font-bold leading-tight">{value}</strong>
      <span className="text-[13px] text-muted">{children}</span>
    </>
  );
  return to ? (
    <a href={to} className="block px-4 py-3 text-ink no-underline hover:bg-hover hover:text-ink">
      {body}
    </a>
  ) : (
    <div className="px-4 py-3">{body}</div>
  );
}

export function Employee({ id }: { id: string }) {
  const S = useS();
  // Свой запрос справочника, а не S.employees шапки: страница знает, когда он загружен, и обновляет его после правки.
  const list = useGet('/employees');
  const emp = listOf(list.data).find((e: any) => e.id === id);
  const name: string = emp?.name ?? id;
  // Оценки есть только у операторов: у специалиста КК и проверяющего диалогов нет, запрос дал бы 404.
  const scores = useGet(list.loading ? null : !emp || emp.role === 'operator' ? `/operators/${encodeURIComponent(name)}` : null);
  const ov = useGet(emp ? '/overview' : null);
  const [editing, setEditing] = useState(false);
  const r: any = scores.data;
  const person = (ov.data as any)?.employees?.find((p: any) => p.id === id);
  const dlg = (did: string) => S.dialogs.find((d: any) => d.id === did);
  const n: number = r ? r.n ?? r.scored ?? 0 : 0;
  const minN: number = r?.min_n ?? 5;
  const enough = r && n >= minN && r.avg_total != null;

  return (
    <>
      <a href="#/people" className="inline-flex w-fit items-center gap-1.5 text-[13px] no-underline">
        <ArrowLeft size={16} aria-hidden="true" /> {t('Все сотрудники')}
      </a>
      <PageHead
        title={name}
        sub={
          emp ? (
            <>
              {roleName(emp.role)}
              {emp.team ? `, ${emp.team}` : ''}
              {emp.active === false && (
                <Chip tone="na" className="ml-2">
                  {t('не работает')}
                </Chip>
              )}
            </>
          ) : (
            t('Оператор из диалогов, в справочнике сотрудников его нет')
          )
        }
      >
        {emp && (
          <>
            <LinkButton size="sm" href={href('audit', null, { actor: emp.id })}>
              <History size={16} aria-hidden="true" /> {t('Журнал действий')}
            </LinkButton>
            <Button size="sm" data-act="edit-employee" onClick={() => setEditing(true)}>
              <Pencil size={16} aria-hidden="true" /> {t('Изменить')}
            </Button>
          </>
        )}
      </PageHead>
      {emp && <EditDialog key={JSON.stringify(emp)} emp={emp} open={editing} onOpenChange={setEditing} onSaved={list.reload} />}

      {list.loading || scores.loading ? (
        <Skeleton className="h-40" />
      ) : scores.error ? (
        <Card className="px-4 py-6 text-muted">{t('Оценок нет: за сотрудником не закреплён ни один диалог. Операторов диалогам назначают импортом CSV на странице «Сотрудники».')}</Card>
      ) : r ? (
        <>
          <Card aria-label={t('Оценки')}>
            <div className="grid grid-cols-2 divide-line2 sm:grid-cols-4 sm:divide-x">
              <Stat value={enough ? f2(r.avg_total) : <span className="text-lg text-muted">{t('недостаточно данных')}</span>}>
                <Term k="total">{t('средний итог')}</Term>{' '}
                {enough && r.sd != null ? t('± {sd}, n={n} из {dialogs} диалогов', { sd: fn(r.sd), n, dialogs: r.dialogs }) : t('n={n} из {dialogs} диалогов', { n, dialogs: r.dialogs })}
                {enough && r.ci95 && (
                  <Tip content={r.definitions?.ci95 ?? t('95% доверительный интервал среднего итога')}>
                    <span tabIndex={0} className="block cursor-help">
                      {t('интервал {lo}–{hi}', { lo: fn(r.ci95[0]), hi: fn(r.ci95[1]) })}
                    </span>
                  </Tip>
                )}
                {!enough && <span className="block">{r.reason ?? t('нужно не меньше {min} оценённых диалогов', { min: minN })}</span>}
              </Stat>
              <Stat value={r.gross_errors}>
                {t('диалогов с')} <Term k="gross">{t('грубыми ошибками')}</Term>
              </Stat>
              <Stat value={r.needs_review}>{t('диалогов: нужна проверка человека')}</Stat>
              <Stat value={r.appeals_open} to="#/appeals">
                {t('апелляций ждут решения')}
              </Stat>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="flex min-w-0 flex-col gap-2 p-4" aria-label={t('Требуют внимания')}>
              <div>
                <h2 className="text-base font-semibold">{t('Требуют внимания')}</h2>
                <p className="text-[13px] text-muted">{t('До трёх критериев с наименьшей долей баллов. Ссылка открывает диалоги, где балл снижен.')}</p>
              </div>
              {r.weakest?.length ? (
                <ul className="m-0 list-none divide-y divide-line2 p-0">
                  {r.weakest.map((w: any) => (
                    <li key={w.cid} className="flex items-center justify-between gap-3 py-2.5">
                      <a href={href('queue', null, { lost: w.cid })} className="text-ink no-underline hover:underline">
                        <span className="text-muted">{w.cid}</span> {w.name}
                      </a>
                      <span className="font-semibold">{pct(w.share)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted">{t('Все оценённые критерии с полным баллом.')}</p>
              )}
            </Card>
            {r.trend?.length ? (
              <Suspense fallback={<Skeleton className="h-56" />}>
                <Chart
                  title={t('Тренд по дням')}
                  caption={t('Средний итог оценённых диалогов за день; в скобках число диалогов. За день с одним-двумя диалогами вывод ненадёжен.')}
                  rows={r.trend.map((x: any) => ({ name: `${x.day} (${x.dialogs})`, value: x.avg_total ?? 0, label: f2(x.avg_total) }))}
                  vertical
                />
              </Suspense>
            ) : (
              <Card className="p-4 text-[13px] text-muted">{t('Тренд появится после оценки диалогов хотя бы за один день.')}</Card>
            )}
          </div>

          {r.dialog_ids?.length > 0 && (
            <Card aria-label={t('Диалоги сотрудника')}>
              <div className="px-4 pb-1.5 pt-4">
                <h2 className="text-base font-semibold">{t('Диалоги')}</h2>
              </div>
              <div className="relative overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>{t('Диалог')}</th>
                      <th>{t('Канал')}</th>
                      <th>{t('Язык')}</th>
                      <th className="num">{t('Итог')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.dialog_ids.map((did: string) => {
                      const d = dlg(did);
                      return (
                        <tr key={did}>
                          <td>
                            <a href={href('d', did)}>{d ? titleOf(d) : did}</a>
                          </td>
                          <td>{d ? (d.ch === 'call' ? t('Звонок') : t('Чат')) : '—'}</td>
                          <td>{d?.lang ?? '—'}</td>
                          <td className="num">{d && S.checklist ? f2(calc(d, S.checklist, S.appeals).total) : '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {r.reasons?.length > 0 && (
            <Card aria-label={t('Причины снижения')}>
              <div className="px-4 pb-1.5 pt-4">
                <h2 className="text-base font-semibold">{t('Причины снижения')}</h2>
                <p className="text-[13px] text-muted">{t('Самые частые формулировки в диалогах сотрудника: темы для разбора на встрече.')}</p>
              </div>
              <ul className="m-0 list-none divide-y divide-line2 p-0">
                {r.reasons.map((x: any) => (
                  <li key={x.tag} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span>{x.tag}</span>
                    <span className="text-[13px] text-muted">
                      {t('диалогов {n}', { n: Array.isArray(x.dialogs) ? x.dialogs.length : x.dialogs })}
                      {x.criteria?.length ? t(', критерии {list}', { list: x.criteria.join(', ') }) : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      ) : null}

      {emp && <Activity person={person} loading={ov.loading} error={ov.error} />}
    </>
  );
}

function Activity({ person, loading, error }: { person: any; loading: boolean; error: string | null }) {
  if (loading) return <Skeleton className="h-32" />;
  if (error || !person) return <Card className="p-4 text-[13px] text-muted">{error ? t('Действия сотрудника недоступны: {error}', { error }) : t('Действия сотрудника недоступны.')}</Card>;
  const acts = [...new Set([...Object.keys(person.week ?? {}), ...Object.keys(person.today ?? {})])].sort((a, b) => (person.week?.[b] ?? 0) - (person.week?.[a] ?? 0));
  return (
    <Card aria-label={t('Действия')}>
      <div className="px-4 pb-1.5 pt-4">
        <h2 className="text-base font-semibold">{t('Действия')}</h2>
        <p className="text-[13px] text-muted">
          {t('Всего: апелляций подано {appeals}, решений {decisions}, ручных ответов {manual}, версий чек-листа {saves}, проверено диалогов {reviewed}.', {
            appeals: person.appeals_filed ?? 0,
            decisions: person.decisions ?? 0,
            manual: person.manual_answers ?? 0,
            saves: person.checklist_saves ?? 0,
            reviewed: person.dialogs_reviewed ?? 0,
          })}
          {person.median_decision_min != null && ' ' + t('Медиана от апелляции до решения: {n} мин.', { n: Math.round(person.median_decision_min) })}
        </p>
      </div>
      {acts.length ? (
        <div className="relative overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>{t('Действие')}</th>
                <th className="num">{t('Сегодня')}</th>
                <th className="num">{t('За 7 дней')}</th>
              </tr>
            </thead>
            <tbody>
              {acts.map(a => (
                <tr key={a}>
                  <td>{actionName(a)}</td>
                  <td className="num">{person.today?.[a] ?? 0}</td>
                  <td className="num">{person.week?.[a] ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 pb-4 text-[13px] text-muted">{t('За 7 дней действий нет.')}</p>
      )}
    </Card>
  );
}

function EditDialog({ emp, open, onOpenChange, onSaved }: { emp: any; open: boolean; onOpenChange: (v: boolean) => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: emp.name, role: emp.role, team: emp.team ?? '', active: emp.active !== false });
  const [busy, setBusy] = useState(false);
  const problem = !f.name.trim() ? t('Укажите имя.') : null;
  async function save() {
    setBusy(true);
    try {
      await api.put(`/employees/${encodeURIComponent(emp.id)}`, { ...f, name: f.name.trim(), team: f.team.trim() });
      toast(t('Сотрудник сохранён.'));
      onOpenChange(false);
      onSaved();
      await refreshOps();
    } catch (e) {
      toast(t('Не сохранено: {error}', { error: e.message }));
    }
    setBusy(false);
  }
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={t('Изменить сотрудника')} description={t('id {id}', { id: emp.id })}>
      <div className="flex flex-col gap-4">
        <Field label={t('Имя')}>
          <input className="fld" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label={t('Роль')}>
          <select className="fld" value={f.role} onChange={e => setF({ ...f, role: e.target.value })}>
            {Object.entries(roleNames()).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('Команда')}>
          <input className="fld" value={f.team} onChange={e => setF({ ...f, team: e.target.value })} />
        </Field>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={f.active} onChange={e => setF({ ...f, active: e.target.checked })} /> {t('Работает: виден в «Вы вошли как»')}
        </label>
        <div className="flex items-center justify-end gap-2.5">
          {problem && <span className="text-[13px] text-risk">{problem}</span>}
          <Button variant="primary" data-act="save-employee" disabled={busy || !!problem} onClick={save}>
            {busy ? t('Сохраняется…') : t('Сохранить')}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
