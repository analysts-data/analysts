// Гибкость чек-листа (design/contract.md, «Настройка чек-листа»): шкала оценок, «что если», песочница,
// нормировка весов, шаблоны критериев и готовые чек-листы. Всё грузится только по действию пользователя:
// на статическом сервере тестов этих путей нет, а 404 — ошибка в консоли.
import { Plus, Trash2, Undo2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ansTxt, f2, loc, titleOf } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { href } from '../../lib/router.js';
import { api, toast } from '../../lib/state.js';
import { rerender, S } from '../../store';
import { Button, Card, Chip, cn, Field, Tip, type Tone } from '../../ui';
import { Dlg } from './Dlg';
import { setDraft } from './Editor';

/** Текст черновика для сравнения: без порядка ключей и пустых полей (сервер читает отсутствие поля как null). */
export const canon = (x: unknown) =>
  JSON.stringify(x, (_, v) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).filter(([, y]) => y != null).sort(([a], [b]) => (a < b ? -1 : 1)))
      : v,
  );

export const bandTone = (x?: string | null): Tone => ({ ok: 'ok', warn: 'ev', risk: 'risk' } as Record<string, Tone>)[x ?? ''] ?? 'na';
const TONES = () => [
  ['', t('Без цвета')],
  ['ok', t('Зелёный')],
  ['warn', t('Янтарный')],
  ['risk', t('Красный')],
];
const signed = (x: number | null) => (x == null ? '' : `${x > 0 ? '+' : ''}${f2(x)}`);
const Head = ({ title, sub, children }: { title: string; sub: string; children?: React.ReactNode }) => (
  <header className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
    <div className="min-w-0">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <p className="text-xs text-muted">{sub}</p>
    </div>
    {children && <span className="flex flex-wrap gap-2">{children}</span>}
  </header>
);

// ---------- Шкала оценок: GET и PUT /api/bands ----------

export function BandsCard({ readOnly }: { readOnly: boolean }) {
  const [b, setB] = useState<any>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      setB(await api.get('/bands'));
    } catch (e) {
      toast(t('Шкала оценок не загружена: {msg}', { msg: e.message }));
    }
  };
  const edit = (f: (n: any) => void) => {
    const n = structuredClone(b);
    f(n);
    setB(n);
  };
  const save = async () => {
    setBusy(true);
    try {
      const body = { bands: b.bands.map((x: any) => ({ min: Number(x.min), label: x.label.trim(), tone: x.tone || null })), why: b.why };
      setB(await api.put('/bands', body));
      setErrs({});
      toast(t('Шкала оценок сохранена.'));
    } catch (e) {
      setErrs(e.body?.fields ?? {});
      toast(e.body?.fields ? t('Шкала оценок не сохранена: исправьте отмеченные поля.') : t('Шкала оценок не сохранена: {msg}', { msg: e.message }));
    } finally {
      setBusy(false);
    }
  };
  const err = (k: string) => errs[k] && <span className="block pt-1 text-xs text-risk">{errs[k]}</span>;

  return (
    <Card aria-label={t('Шкала оценок')} className="divide-y divide-line2">
      <Head title={t('Шкала оценок')} sub={t('Переводит итог диалога в оценку для отчёта руководству. Не входит в чек-лист и не меняет итог.')}>
        {!b ? (
          <Button data-act="bands" onClick={load}>
            {readOnly ? t('Показать шкалу') : t('Настроить шкалу')}
          </Button>
        ) : (
          !readOnly && (
            <Button data-act="bsave" disabled={busy} onClick={save}>
              {t('Сохранить шкалу')}
            </Button>
          )
        )}
      </Head>
      {b && (
        <div className="flex flex-col gap-3 px-4 py-3">
          <span className="text-xs text-muted">
            {b.source === 'saved' && b.saved_at ? t('Сохранена {at}.', { at: new Date(b.saved_at).toLocaleString(loc()) }) : t('Шкала по умолчанию.')}{' '}
            {t('Оценка диалога: первая строка, чью границу итог достигает. Последняя граница 0.')}
          </span>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>{t('Оценка по шкале')}</th>
                  <th className="!text-right">{t('Итог от')}</th>
                  {!readOnly && <th>{t('Цвет')}</th>}
                  {!readOnly && <th />}
                </tr>
              </thead>
              <tbody>
                {b.bands.map((x: any, i: number) => (
                  <tr key={i} data-band={i}>
                    <td>
                      {readOnly ? (
                        <Chip tone={bandTone(x.tone)}>{x.label}</Chip>
                      ) : (
                        <input className="fld" aria-label={t('Название оценки {n}', { n: i + 1 })} value={x.label} onChange={e => edit(n => (n.bands[i].label = e.currentTarget.value))} />
                      )}
                      {err(`bands.${i}.label`)}
                    </td>
                    <td className="num">
                      {readOnly ? (
                        x.min
                      ) : (
                        <input
                          className="fld w-24 text-right"
                          type="number"
                          min={0}
                          max={100}
                          aria-label={t('Граница оценки {n}', { n: i + 1 })}
                          value={x.min}
                          onChange={e => edit(n => (n.bands[i].min = e.currentTarget.value))}
                        />
                      )}
                      {err(`bands.${i}.min`)}
                    </td>
                    {!readOnly && (
                      <td>
                        <select className="fld" aria-label={t('Цвет оценки {n}', { n: i + 1 })} value={x.tone ?? ''} onChange={e => edit(n => (n.bands[i].tone = e.currentTarget.value || null))}>
                          {TONES().map(([v, label]) => (
                            <option key={v} value={v}>
                              {label}
                            </option>
                          ))}
                        </select>
                        {err(`bands.${i}.tone`)}
                      </td>
                    )}
                    {!readOnly && (
                      <td className="w-10">
                        <Tip content={t('Удалить оценку')}>
                          <Button size="sm" variant="ghost" aria-label={t('Удалить оценку')} onClick={() => edit(n => n.bands.splice(i, 1))}>
                            <Trash2 size={16} aria-hidden="true" />
                          </Button>
                        </Tip>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {err('bands')}
          {!readOnly && (
            <span>
              <Button size="sm" variant="ghost" onClick={() => edit(n => n.bands.splice(Math.max(0, n.bands.length - 1), 0, { min: '', label: '', tone: null }))}>
                <Plus size={16} aria-hidden="true" />
                {t('Добавить оценку')}
              </Button>
            </span>
          )}
          {readOnly ? (
            b.why && <p className="text-[13px] text-ink2">{b.why}</p>
          ) : (
            <Field label={t('Почему такие границы')} hint={t('Обоснование для руководства, обязательно.')}>
              <textarea className="fld min-h-[90px]" value={b.why} onChange={e => edit(n => (n.why = e.currentTarget.value))} />
              {err('why')}
            </Field>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------- Проверка черновика: «что если» (POST /api/checklist/simulate) и песочница (POST /api/checklist/trial) ----------

const TRIAL_MAX = 20; // как у сервера: проба на выборке, а не новая оценка набора
const pause = (ms: number) => new Promise(r => setTimeout(r, ms));

export function DraftCheck({ meaning }: { meaning: boolean }) {
  const [sim, setSim] = useState<{ key: string; res: any; crit: string[] | null } | null>(null);
  const [tr, setTr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => void (alive.current = false), []);
  const ids = S.dialogs.filter((d: any) => d.sufficiency?.status !== 'block').slice(0, TRIAL_MAX).map((d: any) => d.id);
  const running = tr?.status === 'running';

  const simulate = async (draft: any, crit: string[] | null = null) => {
    setBusy(true);
    try {
      const res = await api.post('/checklist/simulate', draft);
      if (alive.current) setSim({ key: canon(draft), res, crit });
    } catch (e) {
      toast(t('Расчёт не выполнен: {msg}', { msg: e.message }));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  // ход — GET /api/runs/{id}, как у обычного запуска; после него «что если» с тем же черновиком показывает ответы песочницы
  const trial = async () => {
    const draft = structuredClone(S.draft);
    let run: any;
    try {
      run = await api.post('/checklist/trial', { checklist: draft, dialogs: ids });
    } catch (e) {
      return toast(t('Песочница не запущена: {msg}', { msg: e.message }));
    }
    setTr({ ...run, status: 'running', done: 0, total: 0, errors: [] });
    try {
      for (let p: any = null; p?.status !== 'done' && p?.status !== 'cancelled'; ) {
        await pause(p ? 1000 : 400);
        if (!alive.current) return;
        p = await api.getRun(run.run_id);
        setTr({ ...run, ...p });
      }
    } catch (e) {
      setTr(null);
      return toast(t('Ход песочницы недоступен: {msg}', { msg: e.message }));
    }
    await simulate(draft, run.criteria);
  };

  const stop = () => api.cancelRun(tr.run_id).catch((e: Error) => toast(t('Песочница не остановлена: {msg}', { msg: e.message })));
  const trialWhy = running
    ? t('Песочница уже идёт.')
    : S.run?.status === 'running'
      ? t('Идёт оценка набора: дождитесь её окончания.')
      : !meaning
        ? t('Новых и изменённых по смыслу критериев нет: оценивать нечего, «Посчитать заранее» покажет итоги сразу.')
        : !ids.length
          ? t('Нет диалогов для проверки.')
          : null;

  return (
    <Card aria-label={t('Проверка черновика')} className="divide-y divide-line2">
      <Head title={t('Проверка черновика')} sub={t('Как изменятся итоги и оценки диалогов, если сохранить черновик. Ничего не сохраняется.')}>
        <Button data-act="csim" disabled={busy || running} onClick={() => simulate(structuredClone(S.draft))}>
          {t('Посчитать заранее')}
        </Button>
        <Tip content={trialWhy}>
          <span tabIndex={trialWhy ? 0 : undefined} className="inline-flex">
            <Button data-act="ctrial" disabled={!!trialWhy || busy} onClick={trial}>
              {t('Проверить черновик на {n} диалогах', { n: ids.length })}
            </Button>
          </span>
        </Tip>
      </Head>
      {tr && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-[13px]" data-trial={tr.status}>
          <span>
            {running
              ? t('Песочница: оценено {done} из {total} ответов по критериям {ids}.', { done: tr.done, total: tr.total, ids: tr.criteria.join(', ') })
              : tr.status === 'cancelled'
                ? t('Песочница остановлена: оценено {done} из {total} ответов.', { done: tr.done, total: tr.total })
                : t('Песочница завершена: оценено {done} из {total} ответов по критериям {ids} на {n} диалогах. После сохранения черновика они станут текущими без новой оценки.', {
                    done: tr.done,
                    total: tr.total,
                    ids: tr.criteria.join(', '),
                    n: tr.dialogs.length,
                  })}
            {tr.errors?.length ? ` ${t('Ошибок: {n}.', { n: tr.errors.length })}` : ''}
          </span>
          {running && (
            <Button size="sm" data-act="tstop" onClick={stop}>
              {t('Остановить')}
            </Button>
          )}
        </div>
      )}
      {sim && <SimResult res={sim.res} crit={sim.crit} stale={sim.key !== canon(S.draft)} onHide={() => setSim(null)} />}
    </Card>
  );
}

function SimResult({ res, crit, stale, onHide }: { res: any; crit: string[] | null; stale: boolean; onHide: () => void }) {
  const s = res.summary;
  const tone = (label: string | null) => bandTone(res.bands.find((b: any) => b.label === label)?.tone);
  const band = (label: string | null) => (label == null ? <span className="text-muted">{t('нет итога')}</span> : <Chip tone={tone(label)}>{label}</Chip>);
  const moved = res.dialogs.filter((d: any) => d.band_before !== d.band_after);
  const saveErrs = Object.values(res.save_errors ?? {}) as string[];
  const crOf = (cl: any, id: string) => cl.criteria.find((x: any) => x.id === id);
  // песочница: ответы по её критериям рядом с прежними
  const answers = crit
    ? res.dialogs.flatMap((d: any) => (d.answers ?? []).filter((a: any) => crit.includes(a.id) && a.after != null).map((a: any) => ({ d, a })))
    : [];
  return (
    <div className="flex flex-col gap-3 px-4 py-3" data-sim="">
      <span className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span>
            {t('Средний итог')}{' '}
            <b className="tabular-nums">
              {f2(s.avg_before)} → {f2(s.avg_after)}
            </b>
            {s.delta != null && <span className="text-muted"> ({signed(s.delta)})</span>}
          </span>
          <span className="text-ink2">
            {s.changed
              ? t('Итог изменится у {n} из {total}: выше у {up}, ниже у {down}.', { n: s.changed, total: s.dialogs, up: s.up, down: s.down })
              : t('Итоги диалогов не изменятся.')}
          </span>
          {s.lost_total > 0 && <span className="text-ink2">{t('Без итога до новой оценки: {n}.', { n: s.lost_total })}</span>}
          {stale && <Chip tone="ev">{t('Черновик изменён после расчёта')}</Chip>}
        </span>
        <Button size="sm" variant="ghost" onClick={onHide}>
          {t('Скрыть расчёт')}
        </Button>
      </span>
      {res.insufficient > 0 && <span className="text-xs text-muted">{t('Не учтены диалоги с недостаточными данными: {n}.', { n: res.insufficient })}</span>}
      {saveErrs.length > 0 && (
        <div className="text-[13px]">
          <b className="text-risk">{t('Черновик не сохранится:')}</b>
          <ul className="list-disc pl-5">
            {saveErrs.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>{t('Оценка по шкале')}</th>
                <th className="!text-right">{t('Сейчас')}</th>
                <th className="!text-right">{t('После сохранения')}</th>
              </tr>
            </thead>
            <tbody>
              {res.bands.map((b: any) => (
                <tr key={b.label}>
                  <td>
                    <Chip tone={bandTone(b.tone)}>{b.label}</Chip> <span className="text-xs text-muted">{t('от {min}', { min: b.min })}</span>
                  </td>
                  <td className="num">{b.before}</td>
                  <td className={cn('num', b.before !== b.after && 'font-semibold')}>{b.after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="flex flex-col gap-1 text-[13px] text-ink2">
          {res.moves.map((m: any, i: number) => (
            <li key={i}>{m.text}</li>
          ))}
          {res.pending.map((p: any) => (
            <li key={p.id}>
              {t('Ждёт оценки {id} «{name}»: {why}, без ответа в {n} диалогах.', { id: p.id, name: p.name, why: p.why, n: p.dialogs })}
            </li>
          ))}
          {res.removed.map((r: any) => (
            <li key={r.id}>{t('Удалён {id} «{name}»: его ответы не входят в итог.', { id: r.id, name: r.name })}</li>
          ))}
        </ul>
      </div>
      <h3 className="text-[13px] font-semibold">{moved.length ? t('Сменят оценку: {n}', { n: moved.length }) : t('Ни один диалог не сменит оценку.')}</h3>
      {moved.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>{t('Диалог')}</th>
                <th className="!text-right">{t('Итог')}</th>
                <th>{t('Оценка по шкале')}</th>
                <th>{t('Почему')}</th>
              </tr>
            </thead>
            <tbody>
              {moved.map((d: any) => (
                <tr key={d.id} data-did={d.id}>
                  <td>
                    <a href={href('d', d.id)}>{titleOf(d)}</a>
                  </td>
                  <td className="num">
                    {f2(d.before)} → {f2(d.after)}
                  </td>
                  <td className="whitespace-nowrap">
                    {band(d.band_before)} → {band(d.band_after)}
                  </td>
                  <td className="text-[13px] text-ink2">{d.why.join('; ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {crit && (
        <>
          <h3 className="text-[13px] font-semibold">{t('Ответы песочницы: {n}', { n: answers.length })}</h3>
          {answers.length > 0 && (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>{t('Диалог')}</th>
                    <th>{t('Критерий')}</th>
                    <th>{t('Сейчас')}</th>
                    <th>{t('В песочнице')}</th>
                  </tr>
                </thead>
                <tbody>
                  {answers.map(({ d, a }: any) => {
                    const old = crOf(S.checklist, a.id);
                    return (
                      <tr key={`${d.id}/${a.id}`}>
                        <td>
                          <a href={href('d', d.id)}>{titleOf(d)}</a>
                        </td>
                        <td>
                          {a.id} {a.name}
                        </td>
                        <td>{old && a.before != null ? ansTxt(old, a.before) : '—'}</td>
                        <td className="font-semibold">{ansTxt(crOf(S.draft, a.id) ?? old, a.after)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------- Нормировка: POST /api/checklist/normalize ----------

/** «Привести веса к 100»: веса сервера применяются к черновику, прежние можно вернуть, пока черновик не правили. */
export function Normalize({ sum }: { sum: number }) {
  const [done, setDone] = useState<{ prev: any; key: string; res: any } | null>(null);
  const run = async () => {
    try {
      const res = await api.post('/checklist/normalize', S.draft);
      const w = new Map(res.checklist.criteria.map((c: any) => [c.id, c.w]));
      const prev = S.draft,
        next = structuredClone(prev);
      for (const c of next.criteria) if (c.type !== 'flag' && w.has(c.id)) c.w = w.get(c.id);
      setDraft(next);
      setDone({ prev, key: canon(next), res });
      rerender();
    } catch (e) {
      toast(t('Веса не приведены к 100: {msg}', { msg: e.message }));
    }
  };
  if (done && done.key === canon(S.draft)) {
    const moved = done.res.changes.filter((c: any) => c.from !== c.to);
    return (
      <div className="flex flex-col gap-1" data-norm="">
        <span className="flex flex-wrap items-center gap-2 text-[13px] text-ink2">
          {t('Веса приведены к 100: {list}.', { list: moved.map((c: any) => `${c.id} ${c.from} → ${c.to}`).join(', ') })}
          <Button size="sm" variant="ghost" data-act="cunnorm" onClick={() => (setDraft(done.prev), setDone(null), rerender())}>
            <Undo2 size={16} aria-hidden="true" />
            {t('Вернуть прежние веса')}
          </Button>
        </span>
        <span className="text-xs text-muted">{done.res.explanation}</span>
      </div>
    );
  }
  return sum !== 100 ? (
    <span>
      <Button size="sm" data-act="cnorm" onClick={run}>
        {t('Привести веса к 100')}
      </Button>
    </span>
  ) : null;
}

// ---------- Шаблоны: GET /api/criteria/templates ----------

/** Новый критерий: предложить готовую формулировку из шаблона; «Пустой критерий» оставляет поля как есть. */
export function TemplateOffer({ c }: { c: any }) {
  const [list, setList] = useState<any>(null);
  const [tag, setTag] = useState<string | null>(null);
  const open = async () => {
    try {
      setList(await api.get('/criteria/templates'));
    } catch (e) {
      toast(t('Шаблоны не загружены: {msg}', { msg: e.message }));
    }
  };
  // id и раздел даёт интерфейс: раздел по названию из шаблона, нет такого — новый перед последним («Грубые нарушения»)
  const pick = (x: any) => {
    const dr = S.draft;
    let sec = dr.sections.indexOf(x.section);
    if (sec < 0) {
      sec = Math.max(0, dr.sections.length - 1);
      dr.sections.splice(sec, 0, x.section);
      for (const y of dr.criteria) if (y.sec >= sec) y.sec++;
    }
    dr.criteria[dr.criteria.findIndex((y: any) => y.id === c.id)] = { ...structuredClone(x.criterion), id: c.id, sec };
    setDraft({ ...dr });
    setList(null);
    rerender();
  };
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-surface px-4 py-2.5 text-[13px]">
        <span className="text-ink2">{t('Новый критерий: заполните поля сами или возьмите готовую формулировку из шаблона.')}</span>
        <Button size="sm" data-act="ctpl" onClick={open}>
          {t('Выбрать шаблон')}
        </Button>
      </div>
      {list && (
        <Dlg
          wide
          title={t('Шаблоны критериев')}
          sub={t('Шаблон заполнит критерий {id}: название, текст, тип и предлагаемый вес. Всё можно поправить до сохранения.', { id: c.id })}
          onClose={() => setList(null)}
          footer={
            <Button data-act="tplnone" onClick={() => setList(null)}>
              {t('Пустой критерий')}
            </Button>
          }
        >
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('Тема')}>
            {[null, ...list.tags].map((g: string | null) => (
              <Button key={g ?? ''} size="sm" aria-pressed={tag === g} className={cn(tag === g && 'border-accent bg-accent-soft')} onClick={() => setTag(g)}>
                {g ?? t('Все')}
              </Button>
            ))}
          </div>
          <ul className="flex max-h-[55vh] flex-col divide-y divide-line2 overflow-auto rounded-lg border border-line">
            {list.templates
              .filter((x: any) => !tag || x.tags.includes(tag))
              .map((x: any) => (
                <li key={x.key} className="flex items-start justify-between gap-3 px-3 py-2.5">
                  <div className="min-w-0">
                    <b className="text-sm">{x.criterion.name}</b>
                    <p className="text-xs text-muted">
                      {x.section} · {t('вес {w}', { w: x.criterion.w })}
                      {x.criterion.na ? ', N/A' : ''}
                    </p>
                    <p className="mt-0.5 text-[13px] text-ink2">{x.why}</p>
                  </div>
                  <Button size="sm" data-act="tpl" data-key={x.key} onClick={() => pick(x)}>
                    {t('Взять')}
                  </Button>
                </li>
              ))}
          </ul>
        </Dlg>
      )}
    </>
  );
}

// ---------- Готовые чек-листы: GET /api/checklist/presets ----------

export const loadPresets = () => api.get('/checklist/presets');

export function PresetDlg({ list, onClose }: { list: any[]; onClose: () => void }) {
  // как импорт файла: чек-лист целиком в черновик, version — текущая (иначе черновик сбросится, а сервер ответит 409)
  const load = (p: any) => {
    setDraft({ ...structuredClone(p.checklist), version: S.checklist.version });
    S.cSel = null;
    onClose();
    toast(t('«{name}» в черновике. Проверьте изменения и сохраните как v{v}.', { name: p.name, v: S.checklist.version + 1 }));
  };
  return (
    <Dlg wide title={t('Готовые чек-листы')} sub={t('Чек-лист целиком заменит черновик. Ответы по критериям с прежним смыслом сохранятся.')} onClose={onClose}>
      <ul className="flex flex-col divide-y divide-line2 rounded-lg border border-line">
        {list.map(p => (
          <li key={p.key} className="flex items-start justify-between gap-3 px-3 py-3">
            <div className="min-w-0">
              <span className="flex flex-wrap items-center gap-2">
                <b>{p.name}</b>
                {p.official && <Chip tone="ok">{t('официальный')}</Chip>}
                <span className="text-xs text-muted">{t('критериев: {n}', { n: p.criteria })}</span>
              </span>
              <p className="mt-0.5 text-[13px] text-ink2">{p.description}</p>
            </div>
            <Button size="sm" data-act="preset" data-key={p.key} onClick={() => load(p)}>
              {t('Загрузить')}
            </Button>
          </li>
        ))}
      </ul>
    </Dlg>
  );
}
