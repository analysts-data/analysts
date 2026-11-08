// Меню шапки: тема (светлая, тёмная, системная) и язык интерфейса (русский, английский, казахский). Radix DropdownMenu.
import * as M from '@radix-ui/react-dropdown-menu';
import { Check, Languages, Monitor, Moon, Sun } from 'lucide-react';
import type { ReactNode } from 'react';
import { LANG_SHORT, LANGS, setLang, t, type Lang } from './i18n';
import { S, setThemeMode, themeMode, type ThemeMode } from './store';
import { Tip } from './ui';

const trigger = 'inline-flex h-9 min-w-9 items-center justify-center gap-1.5 rounded-lg border border-line-strong bg-surface px-2 text-[13px] font-semibold text-ink2 hover:bg-hover data-[state=open]:bg-hover';
const content = 'z-[70] min-w-[180px] rounded-lg border border-line bg-surface p-1 text-[13px] text-ink shadow-pop';
const itemCls = 'flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2.5 py-2 outline-none data-[highlighted]:bg-hover';

function Menu({ label, icon, value, children, act }: { label: string; icon: ReactNode; value?: string; children: ReactNode; act: string }) {
  return (
    <M.Root modal={false}>
      <Tip content={label}>
        <M.Trigger className={trigger} aria-label={label} data-act={act}>
          {icon}
          {value && <span>{value}</span>}
        </M.Trigger>
      </Tip>
      <M.Portal>
        <M.Content align="end" sideOffset={6} className={content}>
          <M.Label className="px-2.5 pb-1 pt-1.5 text-xs font-semibold text-muted">{label}</M.Label>
          {children}
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}

const THEMES: [ThemeMode, string, ReactNode][] = [
  ['light', 'Светлая', <Sun size={16} key="l" />],
  ['dark', 'Тёмная', <Moon size={16} key="d" />],
  ['system', 'Как в системе', <Monitor size={16} key="s" />],
];

export function ThemeMenu() {
  const mode = themeMode();
  const icon = THEMES.find(x => x[0] === mode)?.[2];
  return (
    <Menu label={t('Тема оформления')} icon={icon} act="theme">
      <M.RadioGroup value={mode} onValueChange={v => setThemeMode(v as ThemeMode)}>
        {THEMES.map(([k, name, ic]) => (
          <M.RadioItem key={k} value={k} className={itemCls} data-theme-mode={k}>
            <span className="text-muted">{ic}</span>
            <span className="flex-1">{t(name)}</span>
            <M.ItemIndicator>
              <Check size={15} className="text-accent" />
            </M.ItemIndicator>
          </M.RadioItem>
        ))}
      </M.RadioGroup>
    </Menu>
  );
}

export function LangMenu() {
  const lang = (S.lang ?? 'ru') as Lang;
  return (
    <Menu label={t('Язык интерфейса')} icon={<Languages size={16} />} value={LANG_SHORT[lang]} act="lang">
      <M.RadioGroup value={lang} onValueChange={v => setLang(v as Lang)}>
        {(Object.keys(LANGS) as Lang[]).map(k => (
          <M.RadioItem key={k} value={k} className={itemCls} data-lang={k} lang={k}>
            <span className="w-8 text-xs font-semibold text-muted">{LANG_SHORT[k]}</span>
            <span className="flex-1">{LANGS[k]}</span>
            <M.ItemIndicator>
              <Check size={15} className="text-accent" />
            </M.ItemIndicator>
          </M.RadioItem>
        ))}
      </M.RadioGroup>
    </Menu>
  );
}
