// Достаточность данных (Dialog.sufficiency от сервера): чип «Недостаточно данных» (block) или «Мало данных» (flag),
// по клику — причины и основание как есть. Поля нет или status ok — ничего.
import { useState } from 'react';
import { t } from '../lib/i18n.js';
import { Chip, Modal } from '../ui';

export function SufficiencyChip({ d }: { d: any }) {
  const [open, setOpen] = useState(false);
  const s = d.sufficiency;
  if (!s || s.status === 'ok') return null;
  const block = s.status === 'block';
  const label = block ? t('Недостаточно данных') : t('Мало данных');
  return (
    // строка очереди открывает карточку по клику: клик по чипу и окну (портал всплывает по дереву React) до неё не доходит
    <span className="inline-flex" onClick={e => e.stopPropagation()}>
      <button type="button" data-act="sufficiency" data-status={s.status} aria-haspopup="dialog" onClick={() => setOpen(true)}>
        <Chip tone={block ? 'risk' : 'ev'} className="cursor-pointer">
          {label}
        </Chip>
      </button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={t('Почему: {label}', { label })}
        description={block ? t('Диалог не отправляется модели: ответы были бы догадкой. Оцените вручную или дополните данные.') : t('Модель оценивает диалог, но ответы стоит проверить.')}
      >
        <ul className="m-0 flex list-none flex-col divide-y divide-line2 p-0 text-sm" data-why="sufficiency">
          {(s.reasons || []).map((r: any) => (
            <li key={r.id} className="py-2">
              <b>{r.text}</b>
              {r.basis && <p className="mt-0.5 text-[13px] text-muted">{r.basis}</p>}
            </li>
          ))}
        </ul>
      </Modal>
    </span>
  );
}

/** Строка в прогрессе запуска: диалоги, которые не ушли модели из-за недостатка данных (GET /api/runs/{id} → insufficient). */
export function InsufficientNote({ run }: { run: any }) {
  if (!(run?.insufficient > 0)) return null;
  return (
    <span className="basis-full text-xs text-muted" data-run="insufficient">
      {t('Пропущено, недостаточно данных: {n}', { n: run.insufficient })}
    </span>
  );
}
