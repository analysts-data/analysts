// Командная палитра Ctrl+K / ⌘K: диалог по id или названию, экраны, частые действия, тема и роль.
import { Command } from 'cmdk';
import { useEffect } from 'react';
import { titleOf } from './lib/format.js';
import { startRun } from './lib/state.js';
import { applyTheme, currentTheme, go, ROLES, setRole, useS, type Role } from './store';
import { Modal } from './ui';
import { openPaste } from './views/PasteDialog';

const SCREENS: [string, string][] = [
  ['#/queue', 'Диалоги'],
  ['#/appeals', 'Апелляции'],
  ['#/coaching', 'Обучение'],
  ['#/analytics', 'Аналитика'],
  ['#/checklist', 'Чек-лист'],
];

const item = 'flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-sm aria-selected:bg-accent-soft aria-selected:text-accent-ink';
const group = 'px-1 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-muted';

export function Palette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const S = useS();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);

  const run = (f: () => void) => {
    onOpenChange(false);
    f();
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Команды и поиск" description="Диалог по id или названию, экран или действие" wide>
      <Command label="Команды и поиск" className="flex flex-col gap-2">
        <Command.Input autoFocus placeholder="Например: p1-ru-003, апелляции, тёмная тема" className="fld w-full" />
        <Command.List className="max-h-[50vh] overflow-y-auto">
          <Command.Empty className="px-3 py-6 text-center text-sm text-muted">Ничего не найдено</Command.Empty>
          <Command.Group heading="Диалоги" className={group}>
            {S.dialogs.map((d: any) => (
              <Command.Item key={d.id} value={`${d.id} ${titleOf(d)}`} onSelect={() => run(() => go(`#/d/${encodeURIComponent(d.id)}`))} className={item}>
                <span className="truncate">{titleOf(d)}</span>
                <span className="text-xs text-muted">{d.id}</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Экраны" className={group}>
            {SCREENS.map(([h, n]) => (
              <Command.Item key={h} value={`экран ${n}`} onSelect={() => run(() => go(h))} className={item}>
                {n}
              </Command.Item>
            ))}
            <Command.Item value="Грубые ошибки нарушения" onSelect={() => run(() => go('#/queue?grp=risk'))} className={item}>
              Диалоги с грубыми ошибками
            </Command.Item>
          </Command.Group>
          <Command.Group heading="Действия" className={group}>
            {S.role === 'qa' && !S.run?.status?.startsWith('running') && (
              <Command.Item value="Оценить набор запуск" onSelect={() => run(() => startRun({ dialogs: null, criteria: null }))} className={item}>
                Оценить весь набор
              </Command.Item>
            )}
            {S.role === 'qa' && (
              <Command.Item value="Вставить диалог текст новый" onSelect={() => run(openPaste)} className={item}>
                Вставить диалог
              </Command.Item>
            )}
            <Command.Item value="тема тёмная светлая" onSelect={() => run(() => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark', true))} className={item}>
              {currentTheme() === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            </Command.Item>
            {(Object.keys(ROLES) as Role[]).map(r => (
              <Command.Item key={r} value={`роль ${ROLES[r]}`} onSelect={() => run(() => setRole(r))} className={item}>
                Роль: {ROLES[r]}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command>
    </Modal>
  );
}
