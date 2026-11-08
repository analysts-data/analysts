// Редактор чек-листа: черновик S.draft — копия применяемой версии, правки живут в браузере до сохранения.
// Сохранение создаёт новую версию (PUT /api/checklist), ответ pending — критерии, которые ждут оценки модели.
import { ChevronDown, Download, Plus, Save, Upload } from 'lucide-react';
import { useState, type ChangeEvent, type MouseEvent, type ReactNode } from 'react';
import { exportQuestions, importQuestions } from '../lib/checklist_json.js';
import { f2, fn } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { href } from '../lib/router.js';
import { calc } from '../lib/scoring.js';
import { api, cancelRun, failedDialogs, reload, runNote, startRun, toast } from '../lib/state.js';
import { rerender, useS } from '../store';
import { Button, Card, Chip, cn, PageHead, Tip } from '../ui';
import { Dlg } from './checklist/Dlg';
import { Term } from '../terms';
import { Editor, RulesEditor, setDraft, signalChip } from './checklist/Editor';

const typeName = (type: string): string | undefined => ({ bool: t('Да/Нет'), scale: t('Шкала'), flag: t('Грубая ошибка') } as Record<string, string>)[type];
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
// Короткая сводка черновика у кнопки сохранения; полную разницу считает сервер («Что изменится»).
// Правило контракта: вес, название, секция и роль в отчётах новой оценки не требуют.
const NO_REEVAL = new Set(['w', 'name', 'sec', 'signal']);
function summary(cl: any, dr: any) {
  const old = new Map(cl.criteria.map((x: any) => [x.id, x]));
  const parts: string[] = [];
  let reeval = dr.rules !== cl.rules;
  for (const n of dr.criteria) {
    const o: any = old.get(n.id);
    if (!o) {
      parts.push(t('добавлен {id}', { id: n.id }));
      reeval = true;
      continue;
    }
    const keys = [...new Set([...Object.keys(o), ...Object.keys(n)])].filter(k => !same(o[k], n[k]));
    if (!keys.length) continue;
    if (keys.some(k => !NO_REEVAL.has(k))) reeval = true;
    parts.push(keys.length === 1 && keys[0] === 'w' ? t('вес {id}: {from} → {to}', { id: n.id, from: o.w, to: n.w }) : t('изменён {id}', { id: n.id }));
  }
  for (const o of cl.criteria) if (!dr.criteria.some((x: any) => x.id === o.id)) parts.push(t('удалён {id}', { id: o.id }));
  if (!same(cl.sections, dr.sections)) parts.push(t('секции'));
  if (dr.rules !== cl.rules) parts.push(t('общие правила'));
  if (!parts.length) return null;
  const head = parts.length > 4 ? t('{list} и ещё {n}', { list: parts.slice(0, 4).join(', '), n: parts.length - 4 }) : parts.join(', ');
  return `${head[0].toUpperCase()}${head.slice(1)}. ${reeval ? t('Изменённые критерии после сохранения нужно оценить заново.') : t('Итоги пересчитаются без новой оценки.')}`;
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
  // демо без записанных ответов: это не сбой, а ограничение режима, о нём одна понятная строка
  const noRec = S.llmMode === 'replay' && !!errs && errs.errors.every((e: string) => e.includes('Нет записи'));
  const c = dr.criteria.find((x: any) => x.id === S.cSel) || dr.criteria[0];
  S.cSel = c?.id;
  const sum = wsum(scored(dr.criteria));
  const dirty = !same(dr, cl);
  const before = dirty ? avgTotal(S, cl) : null,
    after = dirty ? avgTotal(S, dr) : null;
  // правила входят в смысл каждого критерия: сервер вернёт в pending весь чек-лист
  const changed = (id: string) => dr.rules !== cl.rules || !same(cl.criteria.find((x: any) => x.id === id), dr.criteria.find((x: any) => x.id === id));
  const note = dirty ? summary(cl, dr) : null;
  const nameOf = (id: string) => cl.criteria.find((x: any) => x.id === id)?.name;
  const unscored = S.dialogs.filter((d: any) => pend.some(cid => !d.res[cid])).length;

  const showDiff = async (title: string, load: () => Promise<string>) => {
    try {
      setDiff({ title, md: (await load()).trimEnd() });
    } catch (e) {
      toast(t('Сравнение не получено: {msg}', { msg: e.message }));
    }
  };

  const save = () =>
    busy(S, async () => {
      try {
        const { version, pending } = await api.putChecklist(S.draft);
        S.pending = [...new Set([...(S.pending || []), ...pending])];
        if (S.run?.status !== 'running') S.run = null; // итог прошлого запуска относится к прежней версии
        await reload();
        toast(
          pending.length
            ? t('Сохранена версия v{version}. Критерии {ids} ждут оценки.', { version, ids: pending.join(', ') })
            : t('Сохранена версия v{version}. Итоги пересчитаны без новой оценки модели.', { version }),
        );
      } catch (e) {
        toast(t('Чек-лист не сохранён: {msg}', { msg: e.message }));
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
    if (!Array.isArray(file?.sections) || !Array.isArray(file?.criteria)) return toast(t('Файл не похож на чек-лист: нужны поля sections и criteria.'));
    setDraft({ ...file, version: S.checklist.version });
    S.cSel = null;
    toast(t('Чек-лист из файла в черновике. Проверьте изменения и сохраните как v{v}.', { v: S.checklist.version + 1 }));
  };

  // формат Jev: вопросы сливаются в черновик по ID, несохранённые правки остаются
  const importJev = (e: ChangeEvent<HTMLInputElement>) =>
    busy(S, async () => {
      const text = await readFile(e);
      if (text == null || S.role !== 'qa') return;
      try {
        const result = importQuestions(S.draft, JSON.parse(text));
        setDraft(result.draft);
        toast(t('Добавлено {added}, обновлено {updated}. Проверьте веса и сохраните версию.', { added: result.added, updated: result.updated }));
      } catch (err) {
        toast(t('Импорт не выполнен: {msg}', { msg: err.message }));
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
      if (S.draft.criteria.some((x: any) => x.type === 'flag')) toast(t('Грубые ошибки экспортированы отдельными noul-вопросами с ID «критерий_подвопрос».'));
    } catch (err) {
      toast(t('Экспорт не выполнен: {msg}', { msg: err.message }));
    }
  };

  return (
    <>
      <PageHead
        title={t('Чек-лист качества')}
        sub={
          <>
            <span className="sub">
              {qa ? '' : t('Как оценивается ваша работа.') + ' '}
              <Term k="version">{t('Версия {v}', { v: cl.version })}</Term> {t('применяется к набору. Изменения сохраняются новой версией.')}
            </span>
            {qa && dirty && (
              <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
                <Chip tone="ev">{t('Есть несохранённые изменения')}</Chip>
                {note && <span className="text-ink2">{note}</span>}
                {before != null && after != null && f2(before) !== f2(after) && (
                  <Tip content={t('Средний итог набора сейчас и после сохранения черновика, по уже полученным ответам')}>
                    <span tabIndex={0}>
                      {t('Средний итог {before} →', { before: f2(before) })} <b className="text-ink">{f2(after)}</b>
                    </span>
                  </Tip>
                )}
              </span>
            )}
          </>
        }
      >
        {qa && (
          <Menu label={t('Импорт')} icon={<Upload size={16} aria-hidden="true" />}>
            <label className={cn(item, dirty && 'cursor-not-allowed opacity-45')}>
              {t('Импорт из файла чек-листа (JSON)')}
              <input type="file" accept=".json,application/json" data-act="cimport" className="sr" disabled={dirty} onChange={importJson} />
            </label>
            <label className={cn(item, S.busy && 'cursor-not-allowed opacity-45')}>
              {t('Импорт из формата Jev')}
              <input type="file" accept=".json,application/json" data-act="cjevimport" className="sr" disabled={S.busy} onChange={importJev} />
            </label>
            <span className="px-2.5 pt-1 text-xs text-muted">
              {dirty ? t('Файл чек-листа заменит черновик: сначала сохраните или отмените правки.') : t('Файл чек-листа заменяет черновик.')}{' '}
              {t('Вопросы Jev обновляют его по ID, веса настраиваются отдельно.')}
            </span>
          </Menu>
        )}
        <ExportMenu S={S} onJev={qa ? exportJev : null} />
        {qa && (
          <>
            <Button variant="ghost" data-act="creset" disabled={!dirty} onClick={() => (setDraft(null), rerender())}>
              {t('Отменить изменения')}
            </Button>
            <Button data-act="cwhat" disabled={!dirty} onClick={() => showDiff(t('Что изменится при сохранении v{v}', { v: cl.version + 1 }), () => api.diffDraft(S.draft))}>
              {t('Что изменится')}
            </Button>
            <Button data-act="cadd" onClick={add}>
              <Plus size={16} aria-hidden="true" />
              {t('Добавить критерий')}
            </Button>
            {/* у неактивной кнопки нет событий мыши: подсказку держит обёртка */}
            <Tip content={S.busy ? t('Сохраняем…') : dirty ? null : t('Изменений нет: правьте критерий или общие правила, затем сохраните новую версию.')}>
              <span tabIndex={dirty ? undefined : 0} className="inline-flex">
                <Button variant="primary" data-act="csave" disabled={!dirty || S.busy} onClick={save}>
                  <Save size={16} aria-hidden="true" />
                  {t('Сохранить как v{v}', { v: cl.version + 1 })}
                </Button>
              </span>
            </Tip>
          </>
        )}
      </PageHead>

      {(pend.length > 0 || run || errs) && (
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-ev-line bg-ev-soft p-4" aria-label={t('Оценка набора')}>
          <span>
            {pend.length > 0 && (
              <>
                {pend.length === 1
                  ? t('Критерий {id} «{name}» не оценён', { id: pend[0], name: nameOf(pend[0]) || t('Без названия') })
                  : t('Критерии {ids} не оценены', { ids: pend.join(', ') })}{' '}
                {t('в')} <b>{t('{n} диалогах', { n: unscored })}</b>.{' '}
                {pend.length === 1 ? t('Пока итог считается без него.') : t('Пока итог считается без них.')}{' '}
              </>
            )}
            {run && (
              <>
                {t('Оценено')}{' '}
                <b>{t('{done} из {total}', { done: run.done, total: run.total })}</b>{' '}
                {t('ответов по критериям, ${cost}', { cost: fn(run.cost) })}
                {run.eta_s != null ? t(', осталось около {s} с', { s: Math.ceil(run.eta_s) }) : ''}.
              </>
            )}
          </span>
          {qa && (
            <span className="flex flex-wrap gap-2">
              {run && (
                <Button data-act="stop" onClick={() => cancelRun()}>
                  {t('Остановить')}
                </Button>
              )}
              {pend.length > 0 && (
                <Button
                  variant={dirty || noRec ? 'default' : 'primary'}
                  data-act="crun"
                  disabled={!!run || S.busy}
                  onClick={() => busy(S, () => startRun({ dialogs: null, criteria: waiting(S) }))}
                >
                  {run ? t('Идёт оценка…') : t('Оценить набор')}
                </Button>
              )}
            </span>
          )}
          {errs && <RunErrors run={errs} cids={noRec ? pend : null} />}
        </section>
      )}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.3fr)]">
        <Card className="p-2.5" aria-label={t('Структура чек-листа')}>
          {dr.sections.map((s: string, si: number) => {
            const items = dr.criteria.filter((x: any) => x.sec === si);
            return (
              <div key={si}>
                <p className="flex justify-between px-2.5 pb-1 pt-2 text-xs font-semibold text-muted">
                  <span>{s}</span>
                  <span>{wsum(scored(items)) || ''}</span>
                </p>
                <div className="flex flex-col gap-0.5">
                  {items.map((x: any) => (
                    <button
                      key={x.id}
                      type="button"
                      data-act="csel"
                      data-cid={x.id}
                      aria-current={x.id === S.cSel}
                      onClick={() => ((S.cSel = x.id), rerender())}
                      className={cn(
                        'grid min-h-10 w-full grid-cols-[auto_minmax(0,1fr)_auto_30px] items-center gap-2 rounded-lg px-2.5 py-1.5 text-left',
                        x.id === S.cSel ? 'bg-accent-soft shadow-[inset_0_0_0_1px_var(--accent)]' : 'hover:bg-hover',
                      )}
                    >
                      <span className="text-xs text-muted">{x.id}</span>
                      <span className="flex flex-wrap items-center gap-1">
                        {x.name || <span className="text-muted">{t('Без названия')}</span>}
                        {changed(x.id) && <Chip tone="ev">{t('изменён')}</Chip>}
                        {pend.includes(x.id) && <Chip tone="ev">{t('ждёт оценки')}</Chip>}
                        {x.signal && <Chip tone={x.signal === 'risk' ? 'risk' : 'info'}>{signalChip(x.signal) ?? x.signal}</Chip>}
                      </span>
                      <span className="text-xs text-muted">
                        {typeName(x.type) ?? x.type}
                        {x.na ? ', N/A' : ''}
                      </span>
                      <b className="num">
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
              <Chip tone={sum === 100 ? 'ok' : 'ev'}>{t('Сумма весов {sum}', { sum })}</Chip>
            </span>
            {sum !== 100 && (
              <span className="text-xs text-muted">
                {sum > 100 ? t('Уменьшите другие веса на {n}.', { n: sum - 100 }) : t('Добавьте к весам {n}.', { n: 100 - sum })}{' '}
                {sum > 100
                  ? t('Итог всё равно приводится к 100, но вклад каждого критерия незаметно уменьшится.')
                  : t('Итог всё равно приводится к 100, но вклад каждого критерия незаметно вырастет.')}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1 px-2.5 pb-1 pt-3 text-[13px]">
            <span className="text-xs font-semibold text-muted">
              {t('Версии')}
            </span>
            {S.versions
              .slice()
              .reverse()
              .map((v: any) => (
                <span key={v.v} className="flex flex-wrap items-center gap-1.5">
                  v{v.v}: {v.note}{' '}
                  {v.v === cl.version ? (
                    <Chip tone="ok">
                      {t('применяется')}
                    </Chip>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      data-act="cdiff"
                      data-v={v.v}
                      onClick={() => showDiff(t('Сравнение v{a} с текущей v{b}', { a: v.v, b: cl.version }), () => api.diffVersions(v.v, cl.version))}
                    >
                      {t('Сравнить с текущей')}
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
            {t('Критериев нет.')}
            {qa && <Button onClick={add}>{t('Добавить первый критерий')}</Button>}
          </Card>
        )}
      </div>
      <RulesEditor readOnly={!qa} />

      {diff && (
        <Dlg
          wide
          title={diff.title}
          sub={t('Разницу считает сервер; ничего не сохраняется.')}
          onClose={() => setDiff(null)}
          footer={
            <Button variant="primary" onClick={() => setDiff(null)}>
              {t('Закрыть')}
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
    <Menu label={t('Экспорт')} icon={<Download size={16} aria-hidden="true" />} pop="menu-pop">
      <label className="mb-1 flex flex-col gap-1.5 px-2.5 pt-1">
        <span className="text-[13px] font-semibold text-ink2">
          {t('Сохранённая версия')}
        </span>
        <select className="fld" value={sel} onChange={e => setV(Number(e.currentTarget.value))}>
          {S.versions
            .slice()
            .reverse()
            .map((x: any) => (
              <option key={x.v} value={x.v}>
                v{x.v}
                {x.v === cur ? t(', действует') : ''}
              </option>
            ))}
        </select>
      </label>
      {link('json', 'JSON', { 'data-act': 'cexport', download: '' })}
      {link('csv', 'Excel (CSV)', { 'data-act': 'cmenu', download: '' })}
      {link('md', 'Markdown', { 'data-act': 'cmenu', download: '' })}
      {link('html', t('Памятка для печати'), { 'data-act': 'cmenu', target: '_blank', rel: 'noopener' })}
      {onJev && (
        <>
          <hr className="my-1 border-line2" />
          <button type="button" className={item} data-act="cjevexport" onClick={onJev}>
            {t('Экспорт в формат Jev')}
          </button>
        </>
      )}
    </Menu>
  );
}

// Ошибки запуска: строки «<диалог>: …» или «<диалог>/<критерий>: …», диалог — ссылка на карточку.
// cids — демо без записанных ответов: вместо красного блока строка в янтарном баннере, сырой текст под «Показать ошибки».
// Пути к файлам записей пользователю не нужны.
const noPath = (e: string) => e.replace(/\/\S+\.json/g, '…');
function RunErrors({ run, cids }: { run: any; cids: string[] | null }) {
  const n = run.errors.length;
  const head = run.status === 'running' ? t('Ошибок пока: {n}, в диалогах: {d}.', { n, d: failedDialogs(run.errors).length }) : runNote(run);
  return (
    <div className={cn('flex basis-full flex-col gap-1.5', !cids && 'box risk')}>
      {cids ? (
        <span>
          {cids.length
            ? t('В демо-режиме нет записанных ответов для критериев {ids}. Оцените вручную в карточке или включите модель.', { ids: cids.join(', ') })
            : t('В демо-режиме нет записанных ответов модели. Оцените вручную в карточке или включите модель.')}
        </span>
      ) : (
        <b>{head}</b>
      )}
      <details className={cids ? 'text-[13px] text-ink2' : undefined}>
        <summary className="cursor-pointer">{t('Показать ошибки ({n})', { n })}</summary>
        {cids && <p className="mt-1.5">{head}</p>}
        <ul className="mt-1.5 list-disc pl-5 [overflow-wrap:anywhere]">
          {run.errors.map((e: string, i: number) => {
            const id = failedDialogs([e])[0];
            return (
              <li key={i}>
                <a href={href('d', id)}>{id}</a>
                {noPath(e.slice(id.length))}
              </li>
            );
          })}
        </ul>
      </details>
    </div>
  );
}
