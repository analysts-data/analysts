// Окна карточки: ручной ответ (PUT /api/dialogs/{id}/answers/{cid}) и решение по расхождению (POST /api/decisions).
// #dlg и #dlgForm — метки прежней вёрстки, на них опираются тесты.
import type { FormEvent, ReactNode } from 'react';
import { allowed, answerOf, signOf } from '../../lib/appeal.js';
import { ansTxt, f2, titleOf } from '../../lib/format.js';
import { ans, calc } from '../../lib/scoring.js';
import { api, reload, toast } from '../../lib/state.js';
import { S } from '../../store';
import { Button, Field, Modal } from '../../ui';

export type Pending = { kind: 'manual'; c: any } | { kind: 'review'; c: any; val: any } | null;

const totalOf = (id: string) => f2(calc(S.dialogs.find((x: any) => x.id === id), S.checklist, S.appeals).total);

function Form({ onSubmit, onClose, ok, children }: { onSubmit: (fd: FormData) => Promise<void>; onClose: () => void; ok: string; children: ReactNode }) {
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    onClose();
    onSubmit(fd);
  };
  return (
    <div id="dlg">
      <form id="dlgForm" className="flex flex-col gap-4" onSubmit={submit}>
        {children}
        <footer className="flex justify-end gap-2">
          <Button value="cancel" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" variant="primary" value="ok">
            {ok}
          </Button>
        </footer>
      </form>
    </div>
  );
}

export function CardForms({ d, p, onClose }: { d: any; p: Pending; onClose: () => void }) {
  if (!p) return null;
  const { c } = p;
  const sub = `${titleOf(d)}, ${c.id} ${c.name}`;
  if (p.kind === 'manual') {
    const r = d.res[c.id],
      cur = r ? r.a : null,
      before = totalOf(d.id);
    const save = async (fd: FormData) => {
      const on = new Set(fd.getAll('q'));
      const a = c.type === 'flag' ? Object.fromEntries((c.questions || []).map((q: any) => [q.k, on.has(q.k)])) : answerOf(String(fd.get('a')));
      try {
        await api.putAnswer(d.id, c.id, { a, reason: String(fd.get('reason')).trim(), by: signOf(S.role) });
        await reload();
        toast(`Ответ сохранён. Итог ${titleOf(d)}: ${before} → ${totalOf(d.id)}.`);
      } catch (e: any) {
        toast(`Ответ не сохранён: ${e.message}`);
      }
    };
    return (
      <Modal open onOpenChange={v => !v && onClose()} title={r ? 'Исправить оценку' : 'Оценить вручную'} description={sub}>
        <Form onSubmit={save} onClose={onClose} ok="Сохранить ответ">
          {c.type === 'flag' ? (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1 text-[13px] font-semibold text-ink2">Грубые ошибки</legend>
              {(c.questions || []).map((q: any) => (
                <label key={q.k} className="flex items-center gap-2 text-[13px]">
                  <input type="checkbox" name="q" value={q.k} defaultChecked={Boolean(cur && cur[q.k])} /> {q.label}
                </label>
              ))}
            </fieldset>
          ) : (
            <Field label="Ответ">
              <select name="a" className="fld" defaultValue={cur == null ? undefined : String(cur)}>
                {allowed(c).map((v: any) => (
                  <option key={v} value={String(v)}>
                    {ansTxt(c, v)}
                    {c.type === 'scale' && c.stepText && c.stepText[v] ? `: ${c.stepText[v]}` : ''}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Обоснование, по желанию">
            <textarea name="reason" className="fld" placeholder="Что в разговоре подтверждает ответ" />
          </Field>
          <p className="text-xs text-muted">Ручной ответ заменяет ответ модели, повторная оценка моделью его не меняет. Прежний ответ остаётся в истории базы.</p>
        </Form>
      </Modal>
    );
  }
  const from = ans(d, c.id, S.appeals),
    pick = p.val == null,
    keep = p.val === from,
    before = totalOf(d.id);
  const save = async (fd: FormData) => {
    const to = pick ? answerOf(String(fd.get('to'))) : p.val;
    try {
      await api.postReview({ dlg: d.id, cid: c.id, from, to, reason: String(fd.get('reason')).trim(), reviewer: signOf(S.role) });
      await reload();
      toast(`Решение сохранено. Итог ${titleOf(d)}: ${before} → ${totalOf(d.id)}.`);
    } catch (e: any) {
      toast(`Решение не сохранено: ${e.message}`);
    }
  };
  return (
    <Modal open onOpenChange={v => !v && onClose()} title={pick ? 'Изменить ответ' : keep ? 'Оставить оценку модели' : 'Принять второе мнение'} description={sub}>
      <Form onSubmit={save} onClose={onClose} ok="Сохранить решение">
        {pick ? (
          <Field label="Верный ответ">
            <select name="to" className="fld">
              {allowed(c)
                .filter((v: any) => v !== from)
                .map((v: any) => (
                  <option key={v} value={String(v)}>
                    {ansTxt(c, v)}
                  </option>
                ))}
            </select>
          </Field>
        ) : (
          <p className="box na">
            {keep ? (
              <>
                Оценка остаётся <b>{ansTxt(c, p.val)}</b>.
              </>
            ) : (
              <>
                Оценка меняется с <b>{ansTxt(c, from)}</b> на <b>{ansTxt(c, p.val)}</b>.
              </>
            )}{' '}
            Итог: {before} → <b>{f2(calc(d, S.checklist, S.appeals, { cid: c.id, val: p.val }).total)}</b>
          </p>
        )}
        <Field label="Причина решения, обязательно">
          <textarea name="reason" className="fld" required minLength={5} placeholder="Что в разговоре подтверждает этот ответ" />
        </Field>
      </Form>
    </Modal>
  );
}
