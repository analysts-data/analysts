// Выбор строк очереди и «Перепроверить выбранные». Выбор живёт в этом модуле: очередь о нём не знает.
import { titleOf } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { rerender, useS } from '../store';
import { Button } from '../ui';
import { RecheckMenu } from './card/Recheck';

const picked = new Set<string>();
const flip = (id: string, on: boolean) => {
  if (on) picked.add(id);
  else picked.delete(id);
};

/** Ячейка с флажком: клик не открывает карточку (строка очереди открывает её по клику). */
export function PickCell({ d }: { d: any }) {
  useS();
  return (
    <td className="w-8" onClick={e => e.stopPropagation()}>
      <input
        type="checkbox"
        data-act="pick"
        aria-label={t('Выбрать {title}', { title: titleOf(d) })}
        checked={picked.has(d.id)}
        onChange={e => {
          flip(d.id, e.target.checked);
          rerender();
        }}
      />
    </td>
  );
}

/** Заголовок столбца: выбрать или снять все показанные. */
export function PickHead({ ids }: { ids: string[] }) {
  useS();
  const all = ids.length > 0 && ids.every(id => picked.has(id));
  return (
    <th className="w-8">
      <input
        type="checkbox"
        data-act="pick-all"
        aria-label={t('Выбрать все показанные')}
        checked={all}
        onChange={() => {
          ids.forEach(id => flip(id, !all));
          rerender();
        }}
      />
    </th>
  );
}

/** «Выбрано: N», «Перепроверить выбранные» и «Снять выбор»; без выбора ничего. */
export function BulkBar() {
  const S = useS();
  const ids = S.dialogs.map((d: any) => d.id).filter((id: string) => picked.has(id));
  if (!ids.length) return null;
  return (
    <span className="flex flex-wrap items-center gap-2" data-bulk="">
      <span className="text-[13px] text-muted">{t('Выбрано: {n}', { n: ids.length })}</span>
      <RecheckMenu dialogs={ids} label={t('Перепроверить выбранные')} size="sm" />
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          picked.clear();
          rerender();
        }}
      >
        {t('Снять выбор')}
      </Button>
    </span>
  );
}
