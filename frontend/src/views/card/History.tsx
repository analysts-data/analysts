// История оценок критерия: GET /api/dialogs/{id}/history только по клику; «Сделать текущим» — POST /api/results/{id}/restore.
// Строки сервера как есть: новые первыми, current — ответ, который считает итог, stale — ответ прежнему смыслу критерия.
import { useState } from 'react';
import { ansTxt } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { api, reload, toast } from '../../lib/state.js';
import { S } from '../../store';
import { Button, Chip, Tip, type Tone } from '../../ui';
import { tone } from './util';

const when = (s: any) => String(s ?? '').replace('T', ' ').slice(0, 16);
const toneOf = (c: any, a: any): Tone => (c.type === 'flag' ? (Object.values(a || {}).some(Boolean) ? 'risk' : 'ok') : tone(c, a));

export function History({ d, c, lock }: { d: any; c: any; lock: string | null }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [busy, setBusy] = useState<number | 'load' | null>(null);
  const qa = S.role === 'qa';

  const load = async () => {
    setBusy('load');
    try {
      const h = await api.get(`/dialogs/${encodeURIComponent(d.id)}/history`);
      setRows(h?.[c.id] ?? []);
    } catch (e: any) {
      toast(t('История оценок не загрузилась: {err}', { err: e.message }));
    } finally {
      setBusy(null);
    }
  };
  const restore = async (h: any) => {
    setBusy(h.id);
    try {
      await api.post(`/results/${encodeURIComponent(h.id)}/restore`);
    } catch (e: any) {
      setBusy(null);
      return toast(t('Оценка не стала текущей: {err}', { err: e.message }));
    }
    await reload();
    toast(t('Текущая оценка {cid}: {a} от {at}. Итог пересчитан, прежняя осталась в истории.', { cid: c.id, a: ansTxt(c, h.a), at: when(h.created) }));
    await load();
  };

  if (!rows)
    return (
      <div>
        <Button size="sm" variant="ghost" data-act="history" data-cid={c.id} disabled={busy === 'load'} onClick={load}>
          {busy === 'load' ? t('Загружаем историю…') : t('История оценок')}
        </Button>
      </div>
    );
  return (
    <div className="flex flex-col gap-1.5" data-history={c.id}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-ink2">{t('История оценок')}</span>
        <Button size="sm" variant="ghost" onClick={() => setRows(null)}>
          {t('Скрыть')}
        </Button>
      </div>
      {lock && qa && <p className="text-xs text-muted">{lock}</p>}
      {rows.length === 0 ? (
        <p className="text-[13px] text-muted">{t('Оценок по критерию ещё нет.')}</p>
      ) : (
        <ul className="m-0 list-none divide-y divide-line2 rounded-lg border border-line bg-surface p-0">
          {rows.map(h => (
            <li key={h.id} data-rid={h.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-3 py-2">
              <span className="text-[13px]">
                <span className="num">{when(h.created)}</span>
                <span className="text-muted">
                  {' '}
                  · {h.model}
                  {h.run_id != null && t(', запуск {run}', { run: h.run_id })}
                </span>
              </span>
              <span className="row-span-2 justify-self-end">
                {h.current ? (
                  <Chip tone="ok">{t('текущая')}</Chip>
                ) : h.stale ? (
                  <Tip content={t('Ответ дан прежней формулировке критерия: сделать его текущим нельзя.')}>
                    <span tabIndex={0}>
                      <Chip tone="na">{t('прежний смысл')}</Chip>
                    </span>
                  </Tip>
                ) : (
                  qa && (
                    <Button size="sm" data-act="restore" data-rid={h.id} disabled={busy != null || Boolean(lock)} onClick={() => restore(h)}>
                      {busy === h.id ? t('Сохраняем…') : t('Сделать текущим')}
                    </Button>
                  )
                )}
              </span>
              <span className="flex min-w-0 items-center gap-2">
                <Chip tone={toneOf(c, h.a)}>{ansTxt(c, h.a)}</Chip>
                <Tip content={h.why}>
                  <span className="min-w-0 truncate text-xs text-muted">{h.why}</span>
                </Tip>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
