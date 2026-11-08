// Язык интерфейса: русский, английский, казахский. Выбор хранится в cqa.lang; смена перерисовывает приложение целиком.
// Словари en и kk — отдельные куски сборки: русскому интерфейсу они не нужны и грузятся только при выборе языка.
import { setDict } from './lib/i18n.js';
import { load, rerender, S, save } from './store';

export { t } from './lib/i18n.js';

export const LANGS = { ru: 'Русский', en: 'English', kk: 'Қазақша' } as const;
export const LANG_SHORT = { ru: 'RU', en: 'EN', kk: 'ҚАЗ' } as const;
export type Lang = keyof typeof LANGS;

const LOADERS: Record<Exclude<Lang, 'ru'>, () => Promise<{ default: Record<string, string> }>> = {
  en: () => import('./i18n/en.json'),
  kk: () => import('./i18n/kk.json'),
};
const cache: Partial<Record<Lang, Record<string, string>>> = {};
async function dictOf(l: Lang) {
  if (l === 'ru') return null;
  return (cache[l] ??= (await LOADERS[l]()).default);
}

function paint(l: Lang, d: Record<string, string> | null) {
  setDict(l, d);
  S.lang = l;
  document.documentElement.lang = l;
}

export async function setLang(l: Lang) {
  save('cqa.lang', l);
  paint(l, await dictOf(l));
  rerender();
}

/** Сохранённый язык готов: main.tsx рисует приложение после этого, без мигания русским текстом. */
export const langReady: Promise<void> = (async () => {
  const stored = load('cqa.lang');
  const l: Lang = stored === 'en' || stored === 'kk' ? stored : 'ru';
  try {
    paint(l, await dictOf(l));
  } catch {
    paint('ru', null); // кусок словаря не загрузился — интерфейс по-русски
  }
})();
