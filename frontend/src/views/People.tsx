// «Сотрудники»: открытая нагрузка и работа каждого (GET /api/overview), оценки по операторам (GET /api/operators),
// «Требуют внимания» и «Сильные стороны» из отчёта (GET /api/report?format=json, operators), импорт CSV.
// Не рейтинг: таблица операторов по алфавиту, балл только при n ≥ min_n, рядом n и разброс. Страница сотрудника — people/Employee.tsx.
import { Upload } from 'lucide-react';
import { useState } from 'react';
import { f2, fn } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { go, useS } from '../store';
import { Term } from '../terms';
import { Button, Card, Chip, Empty, LinkButton, PageHead, Skeleton, Tip } from '../ui';
import { Employee } from './people/Employee';
import { ImportDialog } from './people/ImportDialog';
import { listOf, pct, roleName, useGet } from './people/net';

const sum = (o: Record<string, number> | undefined) => Object.values(o ?? {}).reduce((s, n) => s + n, 0);
const minutes = (m: number | null) => (m == null ? '—' : m < 60 ? t('{n} мин', { n: Math.round(m) }) : t('{n} ч', { n: fn(Math.round(m / 6) / 10) }));

/** Ссылка на страницу сотрудника: оператор из диалогов связан со справочником по имени. */
export const personHref = (employees: any[], name: string) => href('people', employees?.find(e => e.name === name)?.id ?? name);

/** n оценённых диалогов: поле n (новый контракт) или scored. */
export const nOf = (r: any): number => r.n ?? r.scored ?? 0;
/** Балл сотрудника: при n < min_n — «недостаточно данных», иначе средний итог, разброс и n. */
export function Score({ r, minN = 5 }: { r: any; minN?: number }) {
  const n = nOf(r);
  if (n < minN || r.avg_total == null)
    return (
      <Tip content={r.reason ?? t('Нужно не меньше {min} оценённых диалогов: при меньшем числе одна оценка сильно сдвигает среднее.', { min: minN })}>
        <span tabIndex={0} className="text-muted">
          {t('недостаточно данных')} <span className="text-xs">{t('(n={n})', { n })}</span>
        </span>
      </Tip>
    );
  return (
    <span>
      <b>{f2(r.avg_total)}</b>
      {r.sd != null && <span className="text-muted"> ± {fn(r.sd)}</span>}
      <span className="text-xs text-muted"> {t('(n={n})', { n })}</span>
    </span>
  );
}

function Stat({ value, to, children }: { value: React.ReactNode; to: string; children: React.ReactNode }) {
  return (
    <a href={to} className="block px-4 py-3 text-ink no-underline hover:bg-hover hover:text-ink">
      <strong className="block text-[28px] font-bold leading-tight">{value}</strong>
      <span className="text-[13px] text-muted">{children}</span>
    </a>
  );
}

export function People({ id }: { id: string | null }) {
  if (id) return <Employee id={id} />;
  return <Overview />;
}

/** Блок из отчёта: кому нужна помощь или у кого перенять опыт. Список сервера, без пересчёта в интерфейсе. */
function Picks({ title, caption, rows, minN, employees, label }: { title: string; caption: string; rows: any[]; minN: number; employees: any[]; label: string }) {
  return (
    <Card aria-label={label} className="min-w-0">
      <div className="px-4 pb-1.5 pt-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-[13px] text-muted">{caption}</p>
      </div>
      {rows.length ? (
        <ul className="m-0 list-none divide-y divide-line2 p-0">
          {rows.map(r => (
            <li key={r.operator} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2.5">
              <a href={personHref(employees, r.operator)} className="font-semibold text-ink no-underline hover:underline">
                {r.operator}
              </a>
              <span className="text-[13px]">
                <Score r={r} minN={minN} />
                {r.gross_errors > 0 && (
                  <Chip tone="risk" className="ml-2">
                    {t('грубых ошибок: {n}', { n: r.gross_errors })}
                  </Chip>
                )}
              </span>
              {r.weakest?.length > 0 && <span className="w-full text-xs text-muted">{r.weakest.map((w: any) => `${w.cid} ${w.name} ${pct(w.share)}`).join('; ')}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 pb-4 text-[13px] text-muted">{t('Пока некого показать: нужно больше оценённых диалогов.')}</p>
      )}
    </Card>
  );
}

function Overview() {
  const S = useS();
  const ov = useGet('/overview');
  const ops = useGet('/operators');
  const rep = useGet('/report?format=json');
  const [importing, setImporting] = useState(false);
  const o: any = ov.data;
  const people: any[] = [...(o?.employees ?? [])].sort((a, b) => (a.team || '').localeCompare(b.team || '', 'ru') || a.name.localeCompare(b.name, 'ru'));
  const teams: Record<string, any> = Object.fromEntries((o?.teams ?? []).map((x: any) => [x.team, x]));
  const minN: number = (ops.data as any)?.min_n ?? 5;
  const defs: Record<string, string> = (ops.data as any)?.definitions ?? {};
  // по алфавиту: это справочник, а не рейтинг
  const operators = [...listOf(ops.data)].sort((a, b) => a.operator.localeCompare(b.operator, 'ru'));
  const picks = (rep.data as any)?.operators;

  return (
    <>
      <PageHead title={t('Сотрудники')} sub={t('Кто что сделал, открытая нагрузка и оценки диалогов по операторам')}>
        <Button size="sm" data-act="import" onClick={() => setImporting(true)}>
          <Upload size={16} aria-hidden="true" /> {t('Импортировать CSV')}
        </Button>
      </PageHead>
      <ImportDialog
        open={importing}
        onOpenChange={setImporting}
        onDone={() => {
          ov.reload();
          ops.reload();
          rep.reload();
        }}
      />

      {ov.error ? (
        <div className="box risk" role="alert">
          {t('Обзор работы не загружен: {error}', { error: ov.error })}
        </div>
      ) : !o ? (
        <Skeleton className="h-40" />
      ) : (
        <>
          <Card aria-label={t('Открытая нагрузка')}>
            <div className="px-4 pt-4">
              <h2 className="text-base font-semibold">{t('Открытая нагрузка')}</h2>
              <p className="text-[13px] text-muted">{t('Что ждёт людей прямо сейчас. Число открывает список.')}</p>
            </div>
            <div className="grid grid-cols-1 divide-y divide-line2 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              <Stat to="#/appeals" value={o.workload?.pending_appeals ?? 0}>
                {t('апелляций ждут решения')}
              </Stat>
              <Stat to="#/queue?grp=review" value={o.workload?.needs_review ?? 0}>
                {t('диалогов:')} <Term k="review">{t('нужна проверка человека')}</Term>
              </Stat>
              <Stat to="#/queue" value={o.workload?.unreviewed ?? 0}>
                {t('диалогов не проверены')}
              </Stat>
            </div>
          </Card>

          <Card aria-label={t('Работа сотрудников')}>
            <div className="px-4 pb-1.5 pt-4">
              <h2 className="text-base font-semibold">{t('Работа сотрудников')}</h2>
              <p className="text-[13px] text-muted">{t('Действия из журнала: за сегодня, за 7 дней и всего. Строка открывает страницу сотрудника.')}</p>
            </div>
            {people.length ? (
              <div className="relative overflow-x-auto">
                <table className="tbl min-w-[960px]">
                  <thead>
                    <tr>
                      <th>{t('Сотрудник')}</th>
                      <th>{t('Роль')}</th>
                      <th className="num">{t('Сегодня')}</th>
                      <th className="num">{t('За 7 дней')}</th>
                      <th className="num">{t('Апелляции поданы')}</th>
                      <th className="num">{t('Решения')}</th>
                      <th className="num">{t('Медиана до решения')}</th>
                      <th className="num">{t('Ручные ответы')}</th>
                      <th className="num">{t('Версии чек-листа')}</th>
                      <th className="num">{t('Проверено диалогов')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {people.map((p, i) => {
                      const tm = teams[p.team];
                      const head = i === 0 || people[i - 1].team !== p.team;
                      return [
                        head && (
                          <tr key={`team:${p.team}`} className="grp">
                            <td colSpan={10}>
                              {p.team || t('Без команды')}
                              {tm && <span className="ml-2 font-normal text-muted">{t('сотрудников {n}, действий сегодня {today}, за 7 дней {week}', { n: tm.employees, today: tm.today, week: tm.week })}</span>}
                            </td>
                          </tr>
                        ),
                        <tr key={p.id} className="click" data-id={p.id} onClick={e => !(e.target as HTMLElement).closest('a') && go(href('people', p.id))}>
                          <td>
                            <a href={href('people', p.id)} className="font-semibold text-ink no-underline hover:underline">
                              {p.name}
                            </a>
                            {p.active === false && (
                              <Chip tone="na" className="ml-2">
                                {t('не работает')}
                              </Chip>
                            )}
                          </td>
                          <td>{roleName(p.role)}</td>
                          <td className="num">{sum(p.today)}</td>
                          <td className="num">{sum(p.week)}</td>
                          <td className="num">{p.appeals_filed ?? 0}</td>
                          <td className="num">{p.decisions ?? 0}</td>
                          <td className="num">{minutes(p.median_decision_min)}</td>
                          <td className="num">{p.manual_answers ?? 0}</td>
                          <td className="num">{p.checklist_saves ?? 0}</td>
                          <td className="num">{p.dialogs_reviewed ?? 0}</td>
                        </tr>,
                      ];
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty action={<Button onClick={() => setImporting(true)}>{t('Импортировать CSV')}</Button>}>{t('Справочник сотрудников пуст.')}</Empty>
            )}
            {(o.unattributed?.today || o.unattributed?.week) > 0 && (
              <p className="px-4 pb-4 pt-2 text-[13px] text-muted">
                {t('Действия без входа: сегодня {today}, за 7 дней {week}. Выберите себя в «Вы вошли как», чтобы действия попадали в учёт.', { today: o.unattributed.today, week: o.unattributed.week })}
              </p>
            )}
          </Card>
        </>
      )}

      {picks && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Picks
            label={t('Требуют внимания')}
            title={t('Требуют внимания')}
            caption={t('Кому нужна помощь: самый низкий средний итог среди сотрудников с достаточным числом оценок.')}
            rows={picks.attention ?? []}
            minN={minN}
            employees={S.employees}
          />
          <Picks
            label={t('Сильные стороны')}
            title={t('Сильные стороны')}
            caption={t('У кого перенять опыт: разберите их диалоги на встрече команды.')}
            rows={picks.strengths ?? picks.best ?? []}
            minN={minN}
            employees={S.employees}
          />
        </div>
      )}

      <Card aria-label={t('Оценки по операторам')}>
        <div className="px-4 pb-1.5 pt-4">
          <h2 className="text-base font-semibold">{t('Оценки по операторам')}</h2>
          <p className="text-[13px] text-muted">
            {t('Средний итог оценённых диалогов с учётом решений. Балл показан при {min} и более оценках, рядом разброс и n. Диалоги без оператора собраны в «Не указан».', { min: minN })}
          </p>
        </div>
        {ops.error ? (
          <p className="px-4 pb-4 text-[13px] text-muted">{t('Оценки по операторам недоступны: {error}', { error: ops.error })}</p>
        ) : ops.loading ? (
          <Skeleton className="m-4 h-24" />
        ) : operators.length ? (
          <div className="relative overflow-x-auto">
            <table className="tbl min-w-[760px]">
              <thead>
                <tr>
                  <th>{t('Оператор')}</th>
                  <th className="num">{t('Диалогов')}</th>
                  <th className="num">
                    <Tip content={defs.sd ? `${defs.n ?? ''} ${defs.sd}`.trim() : t('± — стандартное отклонение итога, n — оценённые диалоги')}>
                      <span tabIndex={0} className="cursor-help underline decoration-line-strong decoration-dotted underline-offset-[3px]">
                        {t('Средний итог')}
                      </span>
                    </Tip>
                  </th>
                  <th className="num">
                    <Term k="gross">{t('Грубые ошибки')}</Term>
                  </th>
                  <th className="num">{t('Нужна проверка')}</th>
                  <th className="num">{t('Апелляции открыты')}</th>
                  <th>{t('Слабые критерии')}</th>
                </tr>
              </thead>
              <tbody>
                {operators.map((r: any) => {
                  const to = personHref(S.employees, r.operator);
                  return (
                    <tr key={r.operator} className="click" data-operator={r.operator} onClick={e => !(e.target as HTMLElement).closest('a, [tabindex]') && go(to)}>
                      <td>
                        <a href={to} className="font-semibold text-ink no-underline hover:underline">
                          {r.operator}
                        </a>
                      </td>
                      <td className="num">{r.dialogs}</td>
                      <td className="num">
                        <Score r={r} minN={minN} />
                      </td>
                      <td className={`num ${r.gross_errors ? 'font-semibold text-risk' : ''}`}>{r.gross_errors}</td>
                      <td className="num">{r.needs_review}</td>
                      <td className="num">{r.appeals_open}</td>
                      <td className="text-[13px]">{(r.weakest ?? []).map((w: any) => `${w.cid} ${w.name} ${pct(w.share)}`).join('; ') || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty action={<LinkButton href="#/queue">{t('Перейти к диалогам')}</LinkButton>}>{t('Оценённых диалогов пока нет.')}</Empty>
        )}
      </Card>
    </>
  );
}
