// Окно апелляции по критерию; открывается кнопкой [data-act="appeal"][data-cid] в карточке.
// Поведение как в web/js/appeal_form.js: критерии без апелляции на рассмотрении, просимый ответ без текущего,
// у флага флажок по каждому вопросу; комментарий от 10 символов.
import { useState, type FormEvent } from 'react';
import { allowed, answerOf, signOf } from '../lib/appeal.js';
import { ansTxt, titleOf } from '../lib/format.js';
import { ans } from '../lib/scoring.js';
import { api, reload, toast } from '../lib/state.js';
import { useS } from '../store';
import { Button, Field, Modal } from '../ui';

const MIN_COMMENT = 10;

export function AppealDialog({ dialog, cid, onClose }: { dialog: any; cid: string | null; onClose: () => void }) {
  if (!cid || !dialog) return null;
  return (
    <Modal open onOpenChange={v => !v && onClose()} title="Оспорить оценку" description={<AppealSub d={dialog} />}>
      <AppealForm key={cid} d={dialog} cid={cid} onClose={onClose} />
    </Modal>
  );
}

function AppealSub({ d }: { d: any }) {
  const S = useS();
  return (
    <>
      {titleOf(d)}, подаёт: {signOf(S.role)}
    </>
  );
}

function AppealForm({ d, cid: first, onClose }: { d: any; cid: string; onClose: () => void }) {
  const S = useS();
  const [cid, setCid] = useState(first);
  const [comment, setComment] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = (id: string) => S.appeals.some((a: any) => a.dlg === d.id && a.cid === id && a.status === 'pending');
  const cs = S.checklist.criteria.filter((c: any) => d.res[c.id] && !pending(c.id));
  const c = S.checklist.criteria.find((x: any) => x.id === cid);
  const a = ans(d, cid, S.appeals);
  const lines = (d.lines || []).filter((l: any) => !l.fold && l.who !== 'system');

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const on = new Set(f.getAll('fq'));
    const ask = c.type === 'flag' ? Object.fromEntries((c.questions || []).map((q: any) => [q.k, on.has(q.k)])) : answerOf(String(f.get('ask')));
    const ev = f.get('ev');
    setBusy(true);
    try {
      await api.postAppeal({ dlg: d.id, cid, ask, ev: ev ? [Number(ev)] : [], comment: comment.trim(), by: signOf(S.role) });
    } catch (x: any) {
      setErr(`Апелляция не отправлена: ${x.message}`);
      setBusy(false);
      return;
    }
    onClose();
    await reload();
    toast(`Апелляция по критерию «${c.name}» отправлена проверяющему.`);
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={send}>
      <Field label="Критерий">
        <select name="cid" className="fld" data-act="acid" value={cid} onChange={e => setCid(e.target.value)}>
          {cs.map((x: any) => (
            <option key={x.id} value={x.id}>
              {x.id} {x.name}
            </option>
          ))}
        </select>
      </Field>
      <p className="box na">
        Сейчас: <b>{ansTxt(c, a)}</b>. {c.type === 'flag' ? '' : d.res[cid]?.why || ''}
      </p>
      {/* key: при смене критерия поля просимого ответа начинаются заново */}
      <div key={cid}>
        {c.type === 'flag' ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1.5 text-[13px] font-semibold text-ink2">Какие нарушения были на самом деле</legend>
            {(c.questions || []).map((q: any) => (
              <label key={q.k} className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-lg border border-line px-3 hover:bg-hover">
                <input type="checkbox" name="fq" value={q.k} defaultChecked={!!a?.[q.k]} className="h-4 w-4 accent-[var(--accent)]" />
                {q.label}
              </label>
            ))}
            <span className="text-xs text-muted">Отмечено: нарушение было. Снимите отметку, если модель ошиблась.</span>
          </fieldset>
        ) : (
          <Field label="Какой ответ вы считаете верным">
            <select name="ask" className="fld">
              {allowed(c)
                .filter((v: any) => v !== a)
                .map((v: any) => (
                  <option key={v} value={v}>
                    {ansTxt(c, v)}
                  </option>
                ))}
            </select>
          </Field>
        )}
      </div>
      <Field label="Комментарий, обязательно" hint={`Не короче ${MIN_COMMENT} символов`}>
        <textarea
          name="comment"
          className="fld"
          data-act="acomment"
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder={`Почему оценка неверна, со ссылкой на реплику, не короче ${MIN_COMMENT} символов`}
        />
      </Field>
      {lines.length > 0 && (
        <Field label="Реплика в подтверждение">
          <select name="ev" className="fld" defaultValue="">
            <option value="">Не выбрана</option>
            {lines.map((l: any) => (
              <option key={l.n} value={l.n}>
                {l.n}: {l.text.slice(0, 60)}
                {l.text.length > 60 ? '…' : ''}
              </option>
            ))}
          </select>
        </Field>
      )}
      {err && (
        <p className="box risk" role="alert">
          {err}
        </p>
      )}
      <p className="text-xs text-muted">Апелляцию рассмотрит проверяющий. Исходная оценка сохранится, решение и новый итог появятся в карточке рядом с ней.</p>
      <div className="flex justify-end gap-2.5 border-t border-line pt-3">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" data-act="asend" disabled={busy || comment.trim().length < MIN_COMMENT}>
          Отправить апелляцию
        </Button>
      </div>
    </form>
  );
}
