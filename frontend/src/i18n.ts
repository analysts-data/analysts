// Язык интерфейса: русский, английский, казахский. Выбор хранится в cqa.lang; смена перерисовывает приложение целиком.
import en from './i18n/en.json';
import kk from './i18n/kk.json';
import { setDict } from './lib/i18n.js';
import { load, rerender, S, save } from './store';

export { t } from './lib/i18n.js';

export const LANGS = { ru: 'Русский', en: 'English', kk: 'Қазақша' } as const;
export const LANG_SHORT = { ru: 'RU', en: 'EN', kk: 'ҚАЗ' } as const;
export type Lang = keyof typeof LANGS;
const DICTS: Record<Lang, Record<string, string> | null> = { ru: null, en, kk };

function paint(l: Lang) {
  setDict(l, DICTS[l]);
  S.lang = l;
  document.documentElement.lang = l;
}

export function setLang(l: Lang) {
  save('cqa.lang', l);
  paint(l);
  rerender();
}

const stored = load('cqa.lang');
paint(stored === 'en' || stored === 'kk' ? stored : 'ru');
