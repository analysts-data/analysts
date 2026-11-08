// Коды причин решений (design/contract.md, «Коды причин решений»): сводка «Изменено людьми» из GET /api/appeals/stats
// и редактор каталога GET/PUT /api/appeals/reasons для специалиста КК.
import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { msg, t } from '../../lib/i18n.js';
import { api, toast } from '../../lib/state.js';
import { Button, Card, cn, Modal, Tip } from '../../ui';
import { humanError } from '../AppealDialog';

export type Reason = { code: string; label: string; applies: 'changed' | 'confirmed' | 'both' };

// К какому исходу решения подходит причина: ключ — applies каталога.
export const APPLIES: [Reason['applies'], string][] = [
  ['changed', msg('Оценка изменена')],
  ['confirmed', msg('Оценка подтверждена')],
  ['both', msg('Любое решение')],
];

const pct = (s: number | null | undefined) => (s == null ? '—' : `${Math.round(s * 100)}%`);
const TOP = 5;

/** «Изменено людьми»: доля пар диалог × критерий, где ответ модели заменили решением или ручным ответом. */
export function Changed({ stats }: { stats: any }) {
  const [all, setAll] = useState(false);
  const m = stats?.modified;
  if (!m?.pairs) return null;
  const crit: any[] = m.criteria ?? [];
  const why: any[] = stats.reasons ?? [];
  const langs: any[] = m.langs ?? [];
  const top = all ? undefined : TOP;
  const more = (n: number) =>
    n > TOP && (
      <button type="button" className="pt-2 text-xs font-semibold text-accent hover:text-accent-ink" onClick={() => setAll(!all)}>
        {all ? t('Свернуть') : t('Показать ещё {n}', { n: n - TOP })}
      </button>
    );
  const quiet = !m.changed && !why.length; // пока никто ничего не исправил, таблицы из нулей не нужны
  return (
    <Card className="divide-y divide-line2" aria-label={t('Изменено людьми')} data-act="changed">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-4">
        <h2 className="text-base font-semibold">{t('Изменено людьми')}</h2>
        <b className="text-2xl font-semibold">{pct(m.share)}</b>
        <span className="text-[13px] text-ink2">{t('{changed} из {pairs} ответов модели', { changed: m.changed, pairs: m.pairs })}</span>
        <p className="w-full text-xs text-muted">
          {t('Ответы, которые проверяющий заменил решением по апелляции или специалист исправил вручную. Чем выше доля у критерия, тем хуже модель его понимает.')}
        </p>
      </div>
      {!quiet && (
        <div className="grid gap-x-6 gap-y-4 px-5 py-4 md:grid-cols-2">
          <div className="min-w-0">
            <h3 className="mb-1 text-[13px] font-semibold text-ink2">{t('По критериям, худшие первыми')}</h3>
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>{t('Критерий')}</th>
                    <th className="!text-right">{t('Изменено')}</th>
                    <th className="!text-right">{t('Доля')}</th>
                  </tr>
                </thead>
                <tbody>
                  {crit.slice(0, top).map(c => (
                    <tr key={c.id}>
                      <td>
                        {c.id} {c.name}
                      </td>
                      <td className="num text-right">{t('{changed} из {pairs}', { changed: c.changed, pairs: c.pairs })}</td>
                      <td className="num text-right font-semibold">{pct(c.share)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {more(crit.length)}
            {langs.length > 1 && (
              <p className="pt-2 text-xs text-muted">
                {t('По языкам:')} {langs.map(l => `${l.key} ${pct(l.share)} (${l.changed}/${l.pairs})`).join(', ')}
              </p>
            )}
          </div>
          <div className="min-w-0">
            <h3 className="mb-1 text-[13px] font-semibold text-ink2">{t('Причины решений: {n}', { n: stats.decisions ?? 0 })}</h3>
            {why.length ? (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>{t('Причина')}</th>
                      <th>{t('Критерий')}</th>
                      <th className="!text-right">{t('Решений')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {why.slice(0, top).map(r => (
                      <tr key={`${r.code}-${r.cid}-${r.status}`}>
                        <td>
                          {r.code ? r.label : t('Без кода')}
                          <span className="block text-xs text-muted">{r.status === 'changed' ? t('Оценка изменена') : t('Оценка подтверждена')}</span>
                        </td>
                        <td>
                          <Tip content={r.name}>
                            <span tabIndex={0}>{r.cid}</span>
                          </Tip>
                        </td>
                        <td className="num text-right">{r.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[13px] text-muted">{t('Решений по апелляциям пока нет.')}</p>
            )}
            {more(why.length)}
          </div>
        </div>
      )}
    </Card>
  );
}

/** Каталог кодов причин: PUT заменяет его целиком; старые решения с удалённым кодом остаются как есть. */
export function ReasonsDialog({ reasons, onClose, onSaved }: { reasons: Reason[]; onClose: () => void; onSaved: (r: Reason[]) => void }) {
  const [rows, setRows] = useState<Reason[]>(reasons.length ? reasons : [{ code: '', label: '', applies: 'both' }]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const edit = (i: number, patch: Partial<Reason>) => setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const saved = await api.put('/appeals/reasons', rows);
      toast(t('Коды причин сохранены: {n}.', { n: saved.length }));
      onSaved(saved);
    } catch (x: any) {
      setErr(humanError(x));
      setBusy(false);
    }
  }

  return (
    <Modal open wide onOpenChange={v => !v && onClose()} title={t('Коды причин')} description={t('Проверяющий выбирает код в решении по апелляции; по кодам считается статистика «Изменено людьми».')}>
      <form className="flex flex-col gap-3" onSubmit={save} noValidate>
        <ul className="divide-y divide-line2">
          {rows.map((r, i) => (
            <li key={i} className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2 py-2.5 first:pt-0 sm:grid-cols-[130px_minmax(0,1fr)_210px_auto]" data-reason={r.code}>
              <label className="col-span-2 flex flex-col gap-1 sm:col-span-1">
                <span className={cn('text-xs text-muted', i > 0 && 'sm:sr-only')}>{t('Код')}</span>
                <input className="fld font-mono text-[13px]" value={r.code} maxLength={32} onChange={e => edit(i, { code: e.target.value.trim() })} placeholder="misread" />
              </label>
              <label className="col-span-2 flex flex-col gap-1 sm:col-span-1">
                <span className={cn('text-xs text-muted', i > 0 && 'sm:sr-only')}>{t('Название')}</span>
                <input className="fld" value={r.label} onChange={e => edit(i, { label: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={cn('text-xs text-muted', i > 0 && 'sm:sr-only')}>{t('Подходит к решению')}</span>
                <select className="fld" value={r.applies} onChange={e => edit(i, { applies: e.target.value as Reason['applies'] })}>
                  {APPLIES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {t(l)}
                    </option>
                  ))}
                </select>
              </label>
              <Tip content={t('Удалить код')}>
                <Button variant="ghost" aria-label={t('Удалить код')} disabled={rows.length < 2} onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}>
                  <Trash2 size={16} aria-hidden="true" />
                </Button>
              </Tip>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted">{t('Код: строчная латиница, цифры, _ и -, до 32 знаков. Решения с удалённым кодом остаются в статистике под этим кодом.')}</p>
        {err && <p className="text-[13px] text-risk">{err}</p>}
        <div className="flex flex-wrap justify-between gap-2.5">
          <Button onClick={() => setRows(rs => [...rs, { code: '', label: '', applies: 'both' }])}>
            <Plus size={16} aria-hidden="true" /> {t('Добавить код')}
          </Button>
          <span className="flex gap-2.5">
            <Button onClick={onClose}>{t('Отмена')}</Button>
            <Button type="submit" variant="primary" data-act="reasons-save" disabled={busy}>
              {busy ? t('Сохраняем…') : t('Сохранить коды')}
            </Button>
          </span>
        </div>
      </form>
    </Modal>
  );
}
