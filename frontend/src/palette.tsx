// Командная палитра Ctrl+K / ⌘K: диалог по id или названию, экраны, частые действия, тема и роль.
import { Command } from 'cmdk';
import { useEffect } from 'react';
import { titleOf } from './lib/format.js';
import { api, startRun } from './lib/state.js';
import { msg } from './lib/i18n.js';
import { go, ROLES, setRole, setThemeMode, useS, type Role } from './store';
import { LANGS, setLang, t, type Lang } from './i18n';
import { Modal } from './ui';
import { openPaste } from './views/PasteDialog';

const SCREENS: [string, string][] = [
  ['#/queue', msg('Диалоги')],
  ['#/appeals', msg('Апелляции')],
  ['#/coaching', msg('Обучение')],
  ['#/analytics', msg('Аналитика')],
  ['#/checklist', msg('Чек-лист')],
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
    <Modal open={open} onOpenChange={onOpenChange} title={t('Команды и поиск')} description={t('Диалог по id или названию, экран или действие')} wide>
      <Command label={t('Команды и поиск')} className="flex flex-col gap-2">
        <Command.Input autoFocus placeholder={t('Например: p1-ru-003, апелляции, тёмная тема')} className="fld w-full" />
        <Command.List className="max-h-[50vh] overflow-y-auto">
          <Command.Empty className="px-3 py-6 text-center text-sm text-muted">{t('Ничего не найдено')}</Command.Empty>
          <Command.Group heading={t('Диалоги')} className={group}>
            {S.dialogs.map((d: any) => (
              <Command.Item key={d.id} value={`${d.id} ${titleOf(d)}`} onSelect={() => run(() => go(`#/d/${encodeURIComponent(d.id)}`))} className={item}>
                <span className="truncate">{titleOf(d)}</span>
                <span className="text-xs text-muted">{d.id}</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading={t('Экраны')} className={group}>
            {SCREENS.map(([h, n]) => (
              <Command.Item key={h} value={`экран ${n} ${t(n)}`} onSelect={() => run(() => go(h))} className={item}>
                {t(n)}
              </Command.Item>
            ))}
            <Command.Item value={`Грубые ошибки нарушения ${t('Диалоги с грубыми ошибками')}`} onSelect={() => run(() => go('#/queue?grp=risk'))} className={item}>
              {t('Диалоги с грубыми ошибками')}
            </Command.Item>
          </Command.Group>
          <Command.Group heading={t('Действия')} className={group}>
            {S.role === 'qa' && !S.run?.status?.startsWith('running') && (
              <Command.Item value={`Оценить набор запуск ${t('Оценить весь набор')}`} onSelect={() => run(() => startRun({ dialogs: null, criteria: null }))} className={item}>
                {t('Оценить весь набор')}
              </Command.Item>
            )}
            {S.role === 'qa' && (
              <Command.Item value={`Вставить диалог текст новый ${t('Вставить диалог')}`} onSelect={() => run(openPaste)} className={item}>
                {t('Вставить диалог')}
              </Command.Item>
            )}
            <Command.Item value={`Отчёт для руководства печать PDF ${t('Отчёт для руководства')}`} onSelect={() => run(() => window.open(`${api.base}/report`, '_blank'))} className={item}>
              {t('Отчёт для руководства')}
            </Command.Item>
            <Command.Item value={`Выгрузить оценки CSV ${t('Выгрузить оценки (CSV, строка на диалог)')}`} onSelect={() => run(() => window.open(`${api.base}/scores/export?shape=wide`, '_blank'))} className={item}>
              {t('Выгрузить оценки (CSV, строка на диалог)')}
            </Command.Item>
            <Command.Item value={`Выгрузить оценки CSV длинный ${t('Выгрузить оценки (CSV, строка на критерий)')}`} onSelect={() => run(() => window.open(`${api.base}/scores/export?shape=long`, '_blank'))} className={item}>
              {t('Выгрузить оценки (CSV, строка на критерий)')}
            </Command.Item>
            {(
              [
                ['light', msg('Светлая тема')],
                ['dark', msg('Тёмная тема')],
                ['system', msg('Тема как в системе')],
              ] as const
            ).map(([m, name]) => (
              <Command.Item key={m} value={`theme ${name} ${t(name)}`} onSelect={() => run(() => setThemeMode(m))} className={item}>
                {t(name)}
              </Command.Item>
            ))}
            {(Object.keys(LANGS) as Lang[]).map(l => (
              <Command.Item key={l} value={`язык language тіл ${LANGS[l]}`} onSelect={() => run(() => setLang(l))} className={item}>
                {LANGS[l]}
              </Command.Item>
            ))}
            {(Object.keys(ROLES) as Role[]).map(r => (
              <Command.Item key={r} value={`роль ${ROLES[r]} ${t(ROLES[r])}`} onSelect={() => run(() => setRole(r))} className={item}>
                {t('Роль: {role}', { role: t(ROLES[r]) })}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command>
    </Modal>
  );
}
