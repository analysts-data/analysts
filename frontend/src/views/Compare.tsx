// Сравнение после перепроверки «Только сравнить»: текущий ответ и теневой ответ запуска по каждому критерию
// (GET /api/dialogs/{id}/history, строки shadow с run_id запуска), итог до и после.
// «Сделать текущим» — POST /api/results/{id}/restore, «Принять все» — POST /api/runs/{id}/adopt.
import { useEffect, useState } from 'react';
import { ansTxt, f2, titleOf } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { calc } from '../lib/scoring.js';
import { api, reload, toast } from '../lib/state.js';
import { useS } from '../store';
import { Button, Chip, Modal } from '../ui';
import { skippedNote } from './card/Recheck';

const enc = encodeURIComponent;
const same = (a: any, b: any) => JSON.stringify(a) === JSON.stringify(b);

export function Compare({ run, dialogs, onClose }: { run: any; dialogs: string[]; onClose: () => void }) {
  const S = useS();
  const [hist, setHist] = useState<Record<string, any> | null>(null);
  const [taken, setTaken] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<number | 'all' | null>(null);
  const qa = S.role === 'qa';

  useEffect(() => {
    Promise.all(dialogs.map(id => api.get(`/dialogs/${enc(id)}/history`))).then(
      hs => setHist(Object.fromEntries(dialogs.map((id, i) => [id, hs[i] || {}]))),
      (e: any) => {
        toast(t('История оценок не загрузилась: {err}', { err: e.message }));
        onClose();
      },
    );
  }, [run.id]);

  // по диалогу: строки «было / стало» для критериев, которые запуск оценил
  const blocks = (hist ? dialogs : [])
    .map(id => S.dialogs.find((d: any) => d.id === id))
    .filter(Boolean)
    .map((d: any) => {
      const rows = S.checklist.criteria
        .map((c: any) => {
          const h: any[] = hist![d.id][c.id] || [];
          const after = h.find(x => x.shadow && String(x.run_id) === String(run.id));
          return after && { c, before: h.find(x => x.current), after };
        })
        .filter(Boolean);
      const total = (pick: (r: any) => any) => {
        const res = { ...d.res };
        for (const r of rows) res[r.c.id] = { ...res[r.c.id], a: pick(r) };
        return calc({ ...d, res }, S.checklist, S.appeals).total;
      };
      return { d, rows, before: total(r => r.before?.a), after: total(r => r.after.a) };
    })
    .filter(b => b.rows.length);
  const all = blocks.flatMap(b => b.rows);
  const left = all.filter(r => !taken.has(r.after.id));

  const restore = async (r: any) => {
    setBusy(r.after.id);
    try {
      await api.post(`/results/${enc(r.after.id)}/restore`);
      setTaken(new Set(taken).add(r.after.id));
      await reload();
      toast(t('Текущая оценка {cid}: {a}. Итог пересчитан, прежняя осталась в истории.', { cid: r.c.id, a: ansTxt(r.c, r.after.a) }));
    } catch (e: any) {
      toast(t('Оценка не стала текущей: {err}', { err: e.message }));
    } finally {
      setBusy(null);
    }
  };
  const adoptAll = async () => {
    setBusy('all');
    try {
      const res = await api.post(`/runs/${enc(run.id)}/adopt`, { dialogs });
      setTaken(new Set(all.map(r => r.after.id)));
      await reload();
      toast(t('Принято ответов: {n}, пропущено: {m}.', { n: res?.adopted ?? left.length, m: res?.skipped ?? 0 }));
    } catch (e: any) {
      toast(t('Ответы не приняты: {err}', { err: e.message }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open onOpenChange={v => !v && onClose()} wide title={t('Сравнение перепроверки')} description={t('Новые ответы не меняют итог, пока вы их не примете.')}>
      <div className="flex flex-col gap-4" data-compare={run.id}>
        {skippedNote(run) && (
          <p className="text-[13px] text-muted" data-compare="skipped">
            {skippedNote(run)}
          </p>
        )}
        {!hist ? (
          <p className="text-muted">{t('Загружаем…')}</p>
        ) : !blocks.length ? (
          <p className="text-muted">{t('Перепроверка не дала новых ответов.')}</p>
        ) : (
          blocks.map(b => (
            <section key={b.d.id} className="flex flex-col gap-2" data-compare-dialog={b.d.id}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-[15px] font-semibold">{titleOf(b.d)}</h3>
                <span className="text-[13px]" data-compare="total">
                  {t('Итог')} <span className="num">{f2(b.before)}</span> → <b className="num">{f2(b.after)}</b>
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="tbl text-[13px]">
                  <thead>
                    <tr>
                      <th>{t('Критерий')}</th>
                      <th>{t('Было')}</th>
                      <th>{t('Стало')}</th>
                      <th>{t('Обоснование')}</th>
                      <th>
                        <span className="sr">{t('Действие')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r: any) => {
                      const changed = !same(r.before?.a, r.after.a);
                      return (
                        <tr key={r.c.id} data-cid={r.c.id} data-changed={changed}>
                          <td>
                            <span className="text-muted">{r.c.id}</span> {r.c.name}
                          </td>
                          <td>
                            {r.before ? ansTxt(r.c, r.before.a) : '—'}
                            <span className="block text-xs text-muted">{r.before?.model}</span>
                          </td>
                          <td>
                            {changed ? <Chip tone="ev">{ansTxt(r.c, r.after.a)}</Chip> : ansTxt(r.c, r.after.a)}
                            <span className="block text-xs text-muted">{r.after.model}</span>
                          </td>
                          <td className="min-w-[220px] text-muted">{r.after.why}</td>
                          <td className="text-right">
                            {taken.has(r.after.id) ? (
                              <Chip tone="ok">{t('текущая')}</Chip>
                            ) : (
                              qa && (
                                <Button size="sm" data-act="cmp-restore" data-rid={r.after.id} disabled={busy != null} onClick={() => restore(r)}>
                                  {busy === r.after.id ? t('Сохраняем…') : t('Сделать текущим')}
                                </Button>
                              )
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ))
        )}
        <div className="flex flex-wrap items-center justify-end gap-2.5">
          <span className="mr-auto text-xs text-muted">
            {t('Изменились ответы: {n} из {m}', { n: all.filter(r => !same(r.before?.a, r.after.a)).length, m: all.length })}
          </span>
          <Button onClick={onClose}>{t('Закрыть')}</Button>
          {qa && (
            <Button variant="primary" data-act="cmp-adopt" disabled={busy != null || !left.length} onClick={adoptAll}>
              {busy === 'all' ? t('Принимаем…') : t('Принять все')}
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
