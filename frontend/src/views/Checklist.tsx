// Редактор чек-листа: черновик S.draft — копия применяемой версии, правки живут в браузере до сохранения.
// Сохранение создаёт новую версию (PUT /api/checklist), ответ pending — критерии, которые ждут оценки модели.
import { ChevronDown, Download, GitCompare, Plus, RotateCcw, Save, Upload } from 'lucide-react';
import { useState, type ChangeEvent, type MouseEvent, type ReactNode } from 'react';
import { exportQuestions, importQuestions } from '../lib/checklist_json.js';
import { f2, fn } from '../lib/format.js';
import { href } from '../lib/router.js';
import { calc } from '../lib/scoring.js';
import { api, cancelRun, failedDialogs, reload, runNote, startRun, toast } from '../lib/state.js';
import { rerender, useS } from '../store';
import { Button, Card, Chip, cn, PageHead } from '../ui';
import { Dlg } from './checklist/Dlg';
import { Editor, RulesEditor, setDraft, SIGNAL_CHIP, TIP } from './checklist/Editor';

const TYPE_NAME: Record<string, string> = { bool: 'Да/Нет', scale: 'Шкала', flag: 'Флаг' };
const scored = (cs: any[]) => cs.filter(c => c.type !== 'flag');
const wsum = (cs: any[]) => cs.reduce((s, x) => s + (Number(x.w) || 0), 0);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
// pending приходит только из ответа PUT /api/checklist и держится, пока критерий есть в версии и у диалогов нет его записи
const waiting = (S: any): string[] =>
  (S.pending || []).filter((cid: string) => S.checklist.criteria.some((c: any) => c.id === cid) && S.dialogs.some((d: any) => !d.res[cid]));
// средний итог набора по уже полученным ответам: для черновика — тот же calc с черновиком вместо версии
function avgTotal(S: any, cl: any) {
  const ts = S.dialogs.map((d: any) => calc(d, cl, S.appeals).total).filter((t: any) => Number.isFinite(t));
  return ts.length ? ts.reduce((a: number, b: number) => a + b, 0) / ts.length : null;
}
const item = 'flex min-h-8 w-full cursor-pointer items-center rounded-lg px-2.5 text-left text-[13px] font-semibold text-ink no-underline hover:bg-hover hover:text-ink';
const closeMenu = (e: { currentTarget: HTMLElement }) => {
  const d = e.currentTarget.closest('details');
  if (d) d.open = false;
};

// csave и crun неактивны, пока запрос в пути: двойной клик не создаёт две версии или два запуска
async function busy(S: any, request: () => Promise<unknown>) {
  if (S.busy) return;
  S.busy = true;
  rerender();
  try {
    await request();
  } finally {
    S.busy = false;
    rerender();
  }
}

const readFile = async (e: ChangeEvent<HTMLInputElement>) => {
  const f = e.currentTarget.files?.[0];
  e.currentTarget.value = ''; // тот же файл можно выбрать повторно
  closeMenu(e);
  return f ? (await f.text()).replace(/^﻿/, '') : null;
};

export function Checklist() {
  const S = useS();
  const [diff, setDiff] = useState<{ title: string; md: string } | null>(null);
  // новая версия с сервера сбрасывает черновик; если сохранение упало, правки остаются
  if (S.draft?.version !== S.checklist.version) setDraft(structuredClone(S.checklist));
  const cl = S.checklist,
    dr = S.draft,
    qa = S.role === 'qa';
  const pend = waiting(S),
    run = S.run?.status === 'running' ? S.run : null,
    errs = S.run?.errors?.length ? S.run : null; // запуск с ошибками остаётся на баннере до следующего запуска
  const c = dr.criteria.find((x: any) => x.id === S.cSel) || dr.criteria[0];
  S.cSel = c?.id;
  const sum = wsum(scored(dr.criteria));
  const dirty = !same(dr, cl);
  const before = dirty ? avgTotal(S, cl) : null,
    after = dirty ? avgTotal(S, dr) : null;
  // правила входят в смысл каждого критерия: сервер вернёт в pending весь чек-лист
  const changed = (id: string) => dr.rules !== cl.rules || !same(cl.criteria.find((x: any) => x.id === id), dr.criteria.find((x: any) => x.id === id));
  const nameOf = (id: string) => cl.criteria.find((x: any) => x.id === id)?.name;
  const unscored = S.dialogs.filter((d: any) => pend.some(cid => !d.res[cid])).length;

  const showDiff = async (title: string, load: () => Promise<string>) => {
    try {
      setDiff({ title, md: (await load()).trimEnd() });
    } catch (e) {
      toast(`Сравнение не получено: ${e.message}`);
    }
  };

  const save = () =>
    busy(S, async () => {
      try {
        const { version, pending } = await api.putChecklist(S.draft);
        S.pending = [...new Set([...(S.pending || []), ...pending])];
        if (S.run?.status !== 'running') S.run = null; // итог прошлого запуска относится к прежней версии
        await reload();
        toast(pending.length ? `Сохранена версия v${version}. Критерии ${pending.join(', ')} ждут оценки.` : `Сохранена версия v${version}. Итоги пересчитаны без новой оценки модели.`);
      } catch (e) {
        toast(`Чек-лист не сохранён: ${e.message}`);
      }
    });

  const add = () => {
    const id = String(Math.max(0, ...dr.criteria.map((x: any) => Number(x.id)).filter(Number.isFinite)) + 1).padStart(2, '0');
    dr.criteria.push({ id, sec: Math.max(0, dr.sections.length - 2), name: '', type: 'bool', w: 5, na: false, text: '', channel: 'all' });
    S.cSel = id;
    S.cFocus = true; // редактор поставит фокус в «Название»
    rerender();
  };

  // файл — в черновик с текущей версией (иначе черновик сбросится, а сервер ответит 409); остальное проверит сервер при сохранении
  const importJson = async (e: ChangeEvent<HTMLInputElement>) => {
    const text = await readFile(e);
    if (text == null) return;
    let file: any = null;
    try {
      file = JSON.parse(text);
    } catch {
      /* не JSON */
    }
    if (!Array.isArray(file?.sections) || !Array.isArray(file?.criteria)) return toast('Файл не похож на чек-лист: нужны поля sections и criteria.');
    setDraft({ ...file, version: S.checklist.version });
    S.cSel = null;
    toast(`Чек-лист из файла в черновике. Проверьте изменения и сохраните как v${S.checklist.version + 1}.`);
  };

  // формат Jev: вопросы сливаются в черновик по ID, несохранённые правки остаются
  const importJev = (e: ChangeEvent<HTMLInputElement>) =>
    busy(S, async () => {
      const text = await readFile(e);
      if (text == null || S.role !== 'qa') return;
      try {
        const result = importQuestions(S.draft, JSON.parse(text));
        setDraft(result.draft);
        toast(`Добавлено ${result.added}, обновлено ${result.updated}. Проверьте веса и сохраните версию.`);
      } catch (err) {
        toast(`Импорт не выполнен: ${err.message}`);
      }
    });

  const exportJev = (e: MouseEvent<HTMLElement>) => {
    closeMenu(e);
    try {
      const blob = new Blob([JSON.stringify(exportQuestions(S.draft), null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob),
        link = document.createElement('a');
      link.href = url;
      link.download = `questions-v${S.draft.version}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (S.draft.criteria.some((x: any) => x.type === 'flag')) toast('Флаги экспортированы отдельными noul-вопросами с ID «критерий_подвопрос».');
    } catch (err) {
      toast(`Экспорт не выполнен: ${err.message}`);
    }
  };

  return (
    <>
      <PageHead
        title="Чек-лист качества"
        sub={
          <span className="sub" title={TIP.version}>
            {qa ? '' : 'Как оценивается ваша работа. '}Версия {cl.version} применяется к набору. Изменения сохраняются новой версией.
          </span>
        }
      >
        {dirty && qa && <Chip tone="ev">Есть несохранённые изменения</Chip>}
        {qa && before != null && after != null && f2(before) !== f2(after) && (
          <span className="text-[13px] text-muted" title="Средний итог по набору сейчас и после сохранения черновика, по уже полученным ответам">
            Средний итог {f2(before)} → <b className="text-ink">{f2(after)}</b>
          </span>
        )}
        {qa && (
          <Menu label="Импорт" icon={<Upload size={16} aria-hidden="true" />}>
            <label className={cn(item, dirty && 'cursor-not-allowed opacity-45')} title={dirty ? 'Сначала сохраните или отмените правки: файл заменит черновик' : undefined}>
              Импорт из файла чек-листа (JSON)
              <input type="file" accept=".json,application/json" data-act="cimport" className="sr" disabled={dirty} onChange={importJson} />
            </label>
            <label className={cn(item, S.busy && 'cursor-not-allowed opacity-45')}>
              Импорт из формата Jev
              <input type="file" accept=".json,application/json" data-act="cjevimport" className="sr" disabled={S.busy} onChange={importJev} />
            </label>
            <span className="px-2.5 pt-1 text-xs text-muted">Файл чек-листа заменяет черновик. Вопросы Jev обновляют его по ID, веса настраиваются отдельно.</span>
          </Menu>
        )}
        <ExportMenu S={S} onJev={qa ? exportJev : null} />
        {qa && (
          <>
            <Button data-act="creset" disabled={!dirty} onClick={() => (setDraft(null), rerender())}>
              <RotateCcw size={16} aria-hidden="true" />
              Отменить изменения
            </Button>
            <Button data-act="cwhat" disabled={!dirty} title="Сервер сравнит черновик с действующей версией; ничего не сохраняется" onClick={() => showDiff(`Что изменится при сохранении v${cl.version + 1}`, () => api.diffDraft(S.draft))}>
              <GitCompare size={16} aria-hidden="true" />
              Что изменится
            </Button>
            <Button data-act="cadd" onClick={add}>
              <Plus size={16} aria-hidden="true" />
              Добавить критерий
            </Button>
            <Button variant="primary" data-act="csave" disabled={!dirty || S.busy} onClick={save}>
              <Save size={16} aria-hidden="true" />
              Сохранить как v{cl.version + 1}
            </Button>
          </>
        )}
      </PageHead>

      {(pend.length > 0 || run || errs) && (
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-ev-line bg-ev-soft p-4" aria-label="Оценка набора">
          <span>
            {pend.length > 0 && (
              <>
                {pend.length === 1 ? `Критерий ${pend[0]} «${nameOf(pend[0]) || 'Без названия'}» не оценён` : `Критерии ${pend.join(', ')} не оценены`} в <b>{unscored} диалогах</b>.
                Пока итог считается без {pend.length === 1 ? 'него' : 'них'}.{' '}
              </>
            )}
            {run && (
              <>
                Оценено{' '}
                <b>
                  {run.done} из {run.total}
                </b>{' '}
                ответов по критериям, ${fn(run.cost)}
                {run.eta_s != null ? `, осталось около ${Math.ceil(run.eta_s)} с` : ''}.
              </>
            )}
          </span>
          {qa && (
            <span className="flex flex-wrap gap-2">
              {run && (
                <Button data-act="stop" onClick={() => cancelRun()}>
                  Остановить
                </Button>
              )}
              {pend.length > 0 && (
                <Button
                  variant={dirty ? 'default' : 'primary'}
                  data-act="crun"
                  disabled={!!run || S.busy}
                  title="Модель оценит только эти критерии; остальные ответы уже есть"
                  onClick={() => busy(S, () => startRun({ dialogs: null, criteria: waiting(S) }))}
                >
                  {run ? 'Идёт оценка…' : 'Оценить набор'}
                </Button>
              )}
            </span>
          )}
          {errs && <RunErrors run={errs} />}
        </section>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.3fr)]">
        <Card className="p-2.5" aria-label="Структура чек-листа">
          {dr.sections.map((s: string, si: number) => {
            const items = dr.criteria.filter((x: any) => x.sec === si);
            return (
              <div key={si}>
                <p className="flex justify-between px-2.5 pb-1 pt-2 text-xs font-semibold text-muted">
                  <span>{s}</span>
                  <span title="Сумма весов секции">{wsum(scored(items)) || ''}</span>
                </p>
                <div className="flex flex-col gap-0.5">
                  {items.map((x: any) => (
                    <button
                      key={x.id}
                      type="button"
                      data-act="csel"
                      data-cid={x.id}
                      aria-current={x.id === S.cSel}
                      title={x.text}
                      onClick={() => ((S.cSel = x.id), rerender())}
                      className={cn(
                        'grid min-h-10 w-full grid-cols-[auto_minmax(0,1fr)_auto_30px] items-center gap-2 rounded-lg px-2.5 py-1.5 text-left',
                        x.id === S.cSel ? 'bg-accent-soft shadow-[inset_0_0_0_1px_var(--accent)]' : 'hover:bg-hover',
                      )}
                    >
                      <span className="text-xs text-muted">{x.id}</span>
                      <span className="flex flex-wrap items-center gap-1">
                        {x.name || <span className="text-muted">Без названия</span>}
                        {changed(x.id) && <Chip tone="ev">изменён</Chip>}
                        {pend.includes(x.id) && <Chip tone="ev">ждёт оценки</Chip>}
                        {x.signal && <Chip tone={x.signal === 'risk' ? 'risk' : 'info'}>{SIGNAL_CHIP[x.signal] ?? x.signal}</Chip>}
                      </span>
                      <span className="text-xs text-muted">
                        {TYPE_NAME[x.type] ?? x.type}
                        {x.na ? ', N/A' : ''}
                      </span>
                      <b className="num" title="Вес">
                        {x.type === 'flag' ? '—' : x.w}
                      </b>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          <div className="mt-2 flex flex-col gap-1 border-t border-line2 px-2.5 pb-1 pt-3">
            <span>
              <Chip tone={sum === 100 ? 'ok' : 'ev'}>Сумма весов {sum}</Chip>
            </span>
            {sum !== 100 && (
              <span className="text-xs text-muted">
                {sum > 100 ? `Уменьшите другие веса на ${sum - 100}.` : `Добавьте к весам ${100 - sum}.`} Итог всё равно приводится к 100, но вклад каждого критерия незаметно {sum > 100 ? 'уменьшится' : 'вырастет'}.
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1 px-2.5 pb-1 pt-3 text-[13px]">
            <span className="text-xs font-semibold text-muted" title={TIP.version}>
              Версии
            </span>
            {S.versions
              .slice()
              .reverse()
              .map((v: any) => (
                <span key={v.v} className="flex flex-wrap items-center gap-1.5">
                  v{v.v}: {v.note}{' '}
                  {v.v === cl.version ? (
                    <Chip tone="ok" title={TIP.version}>
                      применяется
                    </Chip>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      data-act="cdiff"
                      data-v={v.v}
                      title={`Что отличается в v${v.v} от действующей v${cl.version}`}
                      onClick={() => showDiff(`Сравнение v${v.v} с текущей v${cl.version}`, () => api.diffVersions(v.v, cl.version))}
                    >
                      Сравнить с текущей
                    </Button>
                  )}
                </span>
              ))}
          </div>
        </Card>
        {c ? (
          <Editor c={c} readOnly={!qa} />
        ) : (
          <Card className="flex flex-col items-center gap-3 p-10 text-center text-muted">
            Критериев нет.
            {qa && <Button onClick={add}>Добавить первый критерий</Button>}
          </Card>
        )}
      </div>
      <RulesEditor readOnly={!qa} />

      {diff && (
        <Dlg
          wide
          title={diff.title}
          sub="Разницу считает сервер; ничего не сохраняется."
          onClose={() => setDiff(null)}
          footer={
            <Button variant="primary" onClick={() => setDiff(null)}>
              Закрыть
            </Button>
          }
        >
          <pre className="diff max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg bg-sunken p-3 text-[13px]">{diff.md}</pre>
        </Dlg>
      )}
    </>
  );
}

// Меню на <details>: React не управляет open, поэтому перерисовка его не закрывает, а пункт закрывает явно.
function Menu({ label, icon, pop, children }: { label: string; icon: ReactNode; pop?: string; children: ReactNode }) {
  return (
    <details className="menu relative">
      <summary className="inline-flex min-h-10 cursor-pointer list-none items-center gap-2 rounded-lg border border-line-strong bg-surface px-3.5 font-semibold hover:bg-hover [&::-webkit-details-marker]:hidden">
        {icon}
        {label}
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div className={cn(pop, 'absolute right-0 top-[calc(100%+6px)] z-[15] flex w-[280px] max-w-[calc(100vw-32px)] flex-col gap-1 rounded-card border border-line bg-surface p-2 shadow-card')}>{children}</div>
    </details>
  );
}

// Файлы строит сервер (GET /api/checklist/export): пункты — обычные ссылки, по умолчанию применяемая версия.
function ExportMenu({ S, onJev }: { S: any; onJev: ((e: MouseEvent<HTMLElement>) => void) | null }) {
  const [v, setV] = useState<number | null>(null);
  const cur = S.checklist.version,
    sel = v ?? cur;
  const link = (fmt: string, label: string, extra: Record<string, string>) => (
    <a className={item} href={api.exportUrl(sel, fmt)} data-fmt={fmt} onClick={closeMenu} {...extra}>
      {label}
    </a>
  );
  return (
    <Menu label="Экспорт" icon={<Download size={16} aria-hidden="true" />} pop="menu-pop">
      <label className="mb-1 flex flex-col gap-1.5 px-2.5 pt-1">
        <span className="text-[13px] font-semibold text-ink2" title={TIP.version}>
          Сохранённая версия
        </span>
        <select className="fld" value={sel} onChange={e => setV(Number(e.currentTarget.value))}>
          {S.versions
            .slice()
            .reverse()
            .map((x: any) => (
              <option key={x.v} value={x.v}>
                v{x.v}
                {x.v === cur ? ', действует' : ''}
              </option>
            ))}
        </select>
      </label>
      {link('json', 'JSON', { 'data-act': 'cexport', download: '' })}
      {link('csv', 'Excel (CSV)', { 'data-act': 'cmenu', download: '' })}
      {link('md', 'Markdown', { 'data-act': 'cmenu', download: '' })}
      {link('html', 'Памятка для печати', { 'data-act': 'cmenu', target: '_blank', rel: 'noopener' })}
      {onJev && (
        <>
          <hr className="my-1 border-line2" />
          <button type="button" className={item} data-act="cjevexport" title="Вопросы Jev из текущего черновика" onClick={onJev}>
            Экспорт в формат Jev
          </button>
        </>
      )}
    </Menu>
  );
}

// Ошибки запуска: строки «<диалог>: …» или «<диалог>/<критерий>: …», диалог — ссылка на карточку.
function RunErrors({ run }: { run: any }) {
  const n = run.errors.length;
  const head = run.status === 'running' ? `Ошибок пока: ${n}, в диалогах: ${failedDialogs(run.errors).length}.` : runNote(run);
  return (
    <div className="box risk flex basis-full flex-col gap-1.5">
      <b>{head}</b>
      <details>
        <summary className="cursor-pointer">Показать ошибки ({n})</summary>
        <ul className="mt-1.5 list-disc pl-5 [overflow-wrap:anywhere]">
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
