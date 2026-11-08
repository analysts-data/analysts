// Импорт CSV: справочник сотрудников (POST /api/employees/import, `id;name;role;team`) или операторы диалогов
// (POST /api/operators/import, `conversation_id;operator`). Строки проверяются до отправки; текст не теряется при закрытии окна.
import { useState } from 'react';
import { t } from '../../lib/i18n.js';
import { reload, toast } from '../../lib/state.js';
import { refreshOps } from '../../ops';
import { Button, Field, Modal } from '../../ui';
import { postRaw, ROLES } from './net';

type Kind = 'employees' | 'operators';
const kinds = (): Record<Kind, { label: string; columns: string; sample: string }> => ({
  employees: { label: t('Справочник сотрудников'), columns: t('Столбцы: id;name;role;team, разделитель «;»'), sample: 'e1;Алия К.;operator;Поддержка RU' },
  operators: { label: t('Операторы диалогов'), columns: t('Столбцы: conversation_id;operator, разделитель «;» или «,»'), sample: 'call-024;Алия К.' },
});

/** Первая ошибка в CSV или null: та же проверка, что на сервере, чтобы не отправлять заведомо плохой файл. */
export function csvProblem(kind: Kind, text: string): string | null {
  const lines = text
    .split(/\r?\n/)
    .map((l, i) => [i + 1, l.split(kind === 'employees' ? ';' : /[;,]/).map(c => c.trim())] as const)
    .filter(([, c]) => c.some(Boolean));
  const rows = lines.filter(([n, c]) => !(n === lines[0]?.[0] && /^(id|conversation_id)$/i.test(c[0])));
  if (!rows.length) return t('Нет ни одной строки с данными.');
  for (const [n, [id, name, role]] of rows) {
    if (!id) return kind === 'employees' ? t('Строка {n}: нет id сотрудника.', { n }) : t('Строка {n}: нет id диалога.', { n });
    if (kind === 'employees' && !name) return t('Строка {n}: нет имени.', { n });
    if (kind === 'employees' && !ROLES.includes(role)) return t('Строка {n}: роль «{role}» неизвестна, допустимы {roles}.', { n, role: role || '—', roles: ROLES.join(', ') });
  }
  return null;
}

export function ImportDialog({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (v: boolean) => void; onDone: () => void }) {
  const [kind, setKind] = useState<Kind>('employees');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = text.trim() ? csvProblem(kind, text) : null;
  const K = kinds();

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const r = await postRaw(kind === 'employees' ? '/employees/import' : '/operators/import', text);
      toast(
        kind === 'employees'
          ? t('Сотрудники импортированы: добавлено {added}, обновлено {updated}.', { added: r?.added ?? 0, updated: r?.updated ?? 0 })
          : r?.unknown_ids?.length
            ? t('Операторы назначены: {n} диалогов; не найдены: {ids}.', { n: r?.updated ?? 0, ids: r.unknown_ids.join(', ') })
            : t('Операторы назначены: {n} диалогов.', { n: r?.updated ?? 0 }),
      );
      setText('');
      onOpenChange(false);
      onDone();
      refreshOps();
      if (kind === 'operators') await reload();
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={t('Импортировать CSV')} description={t('Файл в UTF-8, строка заголовка необязательна.')}>
      <div className="flex flex-col gap-4">
        <fieldset className="flex flex-wrap gap-4">
          <legend className="sr">{t('Что импортировать')}</legend>
          {(Object.keys(K) as Kind[]).map(k => (
            <label key={k} className="inline-flex items-center gap-2">
              <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} />
              {K[k].label}
            </label>
          ))}
        </fieldset>
        <Field label={t('Файл')} hint={K[kind].columns}>
          <input type="file" accept=".csv,text/csv,text/plain" className="text-[13px]" onChange={async e => e.target.files?.[0] && setText(await e.target.files[0].text())} />
        </Field>
        <Field label={t('Или вставьте строки')} hint={t('Например: {sample}', { sample: K[kind].sample })}>
          <textarea className="fld font-mono text-[13px]" rows={6} value={text} onChange={e => setText(e.target.value)} />
        </Field>
        {(problem || error) && (
          <p className="text-[13px] text-risk" role="alert">
            {problem ?? t('Не импортировано: {error}', { error })}
          </p>
        )}
        <div className="flex items-center justify-end gap-2.5">
          {!text.trim() && <span className="text-[13px] text-muted">{t('Выберите файл или вставьте строки')}</span>}
          <Button variant="primary" data-act="import-send" disabled={busy || !text.trim() || !!problem} onClick={send}>
            {busy ? t('Импортируется…') : t('Импортировать')}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
