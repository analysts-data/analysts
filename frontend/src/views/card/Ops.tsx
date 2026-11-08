// Шапка карточки: оператор, продукт и маркеры из /api/state (полей нет у старого сервера — блока нет).
// Новые эндпоинты зовутся только по клику: справочники при открытии правки, PUT при сохранении. Плюс повторная оценка с force.
import { X } from 'lucide-react';
import { useState } from 'react';
import { titleOf } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { api, reload, runNote, toast } from '../../lib/state.js';
import { rerender, S, useS } from '../../store';
import { Button, Chip, Tip } from '../../ui';
import { Why } from './Why';

const enc = encodeURIComponent;
const items = (x: any): any[] => (Array.isArray(x) ? x : x?.items ?? []);
type Opt = { v: string; t: string };

/** Сервер отдаёт оператора, продукт или маркеры хотя бы у одного диалога: блок показывается. */
export const opsOn = (s: any) => s.dialogs.some((x: any) => 'markers' in x || 'operator' in x || 'product' in x || 'risks' in x);

/** Статус диалога в идущей оценке (GET /api/runs/{id} → dialogs), иначе null. */
export const evalOf = (s: any, id: string): string | null =>
  s.run?.status === 'running' ? s.run.dialogs?.find((x: any) => x.id === id)?.status ?? null : null;

// ponytail: опрос как в startRun (lib/state.js), пока startRun не принимает force; тогда — startRun({..., force: true}).
// Запуск не переживает перезагрузку страницы: ключ cqa.run пишет только startRun.
export async function rerun(d: any) {
  let run: any = null;
  try {
    const { run_id } = await api.post('/runs', { dialogs: [d.id], criteria: null, force: true });
    run = S.run = { id: run_id, done: 0, total: 0, cost: 0, calls: 0, eta_s: null, errors: [], status: 'running', dialogs: [{ id: d.id, status: 'queued' }] };
    toast(t('Повторная оценка {title} запущена. Ручные ответы и решения не меняются.', { title: titleOf(d) }));
    for (let wait = 0; run.status === 'running'; wait = 1000) {
      await new Promise(r => setTimeout(r, wait));
      Object.assign(run, await api.getRun(run_id));
      rerender();
    }
  } catch (e: any) {
    if (run) S.run = null;
    toast(run ? t('Прогресс оценки недоступен: {err}', { err: e.message }) : t('Оценка не запущена: {err}', { err: e.message }));
    return rerender();
  }
  toast(runNote(run) + (run.skipped ? ' ' + t('Не тронуты ручные ответы и решения: {n}.', { n: run.skipped }) : ''));
  await reload();
}

/** Правка по клику: кнопка → поле, «Сохранить» и «Отмена». Варианты (load) грузятся при открытии. */
function Pick({ act, button, label, options, load, free, initial = '', check, save }: {
  act: string;
  button: string;
  label: string;
  options?: Opt[];
  load?: () => Promise<Opt[]>;
  free?: boolean;
  initial?: string;
  check: (v: string, opts: Opt[]) => string;
  save: (v: string) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<Opt[]>(options ?? []);
  const [v, setV] = useState(initial);
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setV(initial);
    if (load) {
      setBusy(true);
      try {
        setOpts(await load());
      } catch (e: any) {
        setBusy(false);
        return toast(t('Список не загрузился: {err}', { err: e.message }));
      }
      setBusy(false);
    }
    setOpen(true);
  };
  if (!open)
    return (
      <Button size="sm" variant="ghost" data-act={act} disabled={busy} onClick={start}>
        {busy ? t('Загружаем…') : button}
      </Button>
    );
  const err = check(v.trim(), options ?? opts);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (err || busy) return;
    setBusy(true);
    try {
      await save(v.trim());
      setOpen(false);
    } catch (e: any) {
      toast(t('Не сохранено: {err}', { err: e.message }));
    } finally {
      setBusy(false);
    }
  };
  const list = options ?? opts;
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={submit}>
      {free ? (
        <>
          <input className="fld !min-h-8 w-48" aria-label={label} list={`dl-${act}`} value={v} maxLength={300} autoFocus onChange={e => setV(e.target.value)} />
          <datalist id={`dl-${act}`}>
            {list.map(o => (
              <option key={o.v} value={o.v}>
                {o.t}
              </option>
            ))}
          </datalist>
        </>
      ) : (
        <select className="fld !min-h-8" aria-label={label} value={v} autoFocus onChange={e => setV(e.target.value)}>
          <option value="">{t('Выберите…')}</option>
          {list.map(o => (
            <option key={o.v} value={o.v}>
              {o.t}
            </option>
          ))}
        </select>
      )}
      <Button size="sm" type="submit" data-act={`${act}-save`} disabled={busy || Boolean(err)}>
        {busy ? t('Сохраняем…') : t('Сохранить')}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        {t('Отмена')}
      </Button>
      {err && <span className="text-xs text-muted">{err}</span>}
    </form>
  );
}

const Item = ({ k, name, children }: { k: string; name: string; children: React.ReactNode }) => (
  <span className="flex flex-wrap items-center gap-2" data-ops-item={name}>
    <span className="text-muted">{k}:</span>
    {children}
  </span>
);

/** Есть что показать в «Почему»: не пустые поля basis. */
const hasBasis = (b: any) => (typeof b === 'string' ? Boolean(b) : b != null && Object.values(b).some(v => v != null && v !== '' && !(Array.isArray(v) && !v.length)));

export function OpsBar({ d, onLine }: { d: any; onLine: (n: number) => void }) {
  const S = useS();
  const [undo, setUndo] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  if (!opsOn(S)) return null;
  const qa = S.role === 'qa';
  const p = d.product;
  const markers: any[] = d.markers || [];
  const people: Opt[] = (S.employees || []).filter((e: any) => e.role === 'operator' && e.active !== false).map((e: any) => ({ v: e.name, t: e.team || '' }));

  const putMarkers = async (body: { add?: string[]; remove?: string[] }) => {
    await api.put(`/dialogs/${enc(d.id)}/markers`, { add: [], remove: [], ...body });
    await reload();
  };
  const unmark = async (m: any) => {
    setBusy(true);
    try {
      await putMarkers({ remove: [m.k] });
      setUndo(m);
    } catch (e: any) {
      toast(t('Маркер не снят: {err}', { err: e.message }));
    } finally {
      setBusy(false);
    }
  };
  const restore = async () => {
    setBusy(true);
    try {
      await putMarkers({ add: [undo.k] });
      setUndo(null);
    } catch (e: any) {
      toast(t('Маркер не возвращён: {err}', { err: e.message }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px]" data-ops="">
      <Item k={t('Оператор')} name="operator">
        {d.operator ? <b data-ops="operator">{d.operator}</b> : <span className="text-muted">{t('не назначен')}</span>}
        {qa && (
          <Pick
            act="operator"
            button={d.operator ? t('Изменить') : t('Назначить')}
            label={t('Оператор')}
            free
            options={people}
            initial={d.operator || ''}
            check={v => (v.length > 200 ? t('Имя не длиннее 200 символов') : !v && !d.operator ? t('Введите имя оператора') : '')}
            save={async v => {
              await api.put(`/dialogs/${enc(d.id)}/operator`, { operator: v || null });
              await reload();
              toast(v ? t('Оператор {name} назначен.', { name: v }) : t('Назначение оператора снято.'));
            }}
          />
        )}
      </Item>

      <Item k={t('Продукт')} name="product">
        {!p ? (
          <span className="text-muted">{t('не определён')}</span>
        ) : p.status === 'pending' ? (
          <span className="text-muted" role="status">
            {t('определяется…')}
          </span>
        ) : p.status === 'error' || !p.name ? (
          <Tip content={p.error ? String(p.error).replace(/\s*\(make record[^)]*\)/, '') : null}>
            <span className="text-muted" tabIndex={p.error ? 0 : undefined}>
              {t('не определён')}
            </span>
          </Tip>
        ) : (
          <>
            <b data-ops="product">{p.name}</b>
            {p.by && <span className="text-muted">{p.by}</span>}
            {p.needs_review && <Chip tone="ev">{t('проверьте')}</Chip>}
            {hasBasis(p.basis) && <Why title={t('Почему продукт «{name}»', { name: p.name })} basis={{ ...p.basis, confidence: p.confidence }} d={d} onLine={onLine} />}
          </>
        )}
        {qa && p?.status !== 'pending' && (
          <Pick
            act="product"
            button={t('Исправить')}
            label={t('Продукт')}
            load={async () => items(await api.get('/products')).map((x: any) => ({ v: x.id, t: x.name }))}
            initial={p?.id || ''}
            check={(v, o) => (!o.length ? t('Справочник продуктов пуст') : !v ? t('Выберите продукт') : v === p?.id ? t('Этот продукт уже указан') : '')}
            save={async v => {
              await api.put(`/dialogs/${enc(d.id)}/product`, { id: v });
              await reload();
              toast(t('Продукт исправлен вручную.'));
            }}
          />
        )}
      </Item>

      <Item k={t('Маркеры')} name="markers">
        {!markers.length && !undo && <span className="text-muted">{t('нет')}</span>}
        {markers.map(m => (
          <span key={m.k} className="inline-flex items-center gap-1" data-marker={m.k}>
            <Chip tone={m.auto ? 'ev' : 'na'}>
              {m.label}
              {qa && (
                <Tip content={t('Снять маркер «{label}»', { label: m.label })}>
                  <button type="button" className="-mr-1 rounded-full hover:bg-hover" data-act="unmark" aria-label={t('Снять маркер «{label}»', { label: m.label })} disabled={busy} onClick={() => unmark(m)}>
                    <X size={14} aria-hidden="true" />
                  </button>
                </Tip>
              )}
            </Chip>
            {m.auto && hasBasis(m.basis) && <Why title={t('Почему маркер «{label}»', { label: m.label })} basis={m.basis} d={d} onLine={onLine} />}
          </span>
        ))}
        {undo && (
          <Button size="sm" variant="ghost" data-act="unmark-undo" disabled={busy} onClick={restore}>
            {t('Вернуть «{label}»', { label: undo.label })}
          </Button>
        )}
        {qa && (
          <Pick
            act="mark"
            button={t('Добавить маркер')}
            label={t('Маркер')}
            load={async () =>
              items(await api.get('/markers/catalog'))
                .filter((x: any) => !markers.some(m => m.k === x.k))
                .map((x: any) => ({ v: x.k, t: x.label }))
            }
            check={(v, o) => (!o.length ? t('Все маркеры каталога уже стоят') : !v ? t('Выберите маркер') : '')}
            save={async v => {
              await putMarkers({ add: [v] });
              setUndo(null);
            }}
          />
        )}
      </Item>
      {(d.risks?.length ?? 0) > 0 && (
        <Item k={t('Риски')} name="risks">
          {d.risks.map((r: any) => (
            <span key={r.k} className="inline-flex items-center gap-1.5" data-risk={r.k}>
              <Chip tone="risk">{r.label}</Chip>
              {r.lines?.length > 0 && (
                <button type="button" className="text-xs font-semibold text-accent hover:text-accent-ink" onClick={() => onLine(r.lines[0])}>
                  {t('Реплика {n}', { n: r.lines[0] })}
                </button>
              )}
              {r.basis && (
                <Tip content={typeof r.basis === 'string' ? r.basis : (r.basis.why ?? '')}>
                  <span tabIndex={0} className="cursor-help text-xs text-muted underline decoration-dotted underline-offset-2">
                    {t('Почему')}
                  </span>
                </Tip>
              )}
            </span>
          ))}
        </Item>
      )}
    </div>
  );
}
