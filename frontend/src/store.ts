// Мост между lib/state.js (единственное хранилище: данные GET /api/state, запуск оценки, toast) и React.
// state.js меняет S и зовёт S.app.render(); здесь это увеличивает версию, и подписанные компоненты перерисовываются.
import { useMemo, useSyncExternalStore } from 'react';
import { S as RAW, toast } from './lib/state.js';
import { parseHash } from './lib/router.js';

// ponytail: данные не типизированы (strict: false), форма — design/contract.md; типы, если появится время.
export const S: any = RAW;

let version = 0;
const subs = new Set<() => void>();
export const rerender = () => {
  version++;
  subs.forEach(f => f());
};
S.app = { render: rerender };

const subscribe = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};

/** S целиком; компонент перерисуется после любого render() из state.js или rerender(). */
export function useS(): any {
  useSyncExternalStore(subscribe, () => version);
  return S;
}

const subscribeHash = (f: () => void) => {
  addEventListener('hashchange', f);
  return () => removeEventListener('hashchange', f);
};

export type Route = { page: string; id: string | null; params: Record<string, string> };

/** Текущий маршрут: parseHash(location.hash), без React Router. */
export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribeHash, () => location.hash);
  return useMemo(() => parseHash(hash), [hash]);
}

export const go = (hash: string) => {
  location.hash = hash;
};

// localStorage только в try/catch: песочница iframe Dynamics и приватный режим его запрещают.
export const load = (k: string) => {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
};
export const save = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* без хранилища — без запоминания */
  }
};

export const ROLES = { qa: 'Специалист КК', operator: 'Оператор', reviewer: 'Проверяющий' } as const;
export type Role = keyof typeof ROLES;
const ROLE_LOWER: Record<Role, string> = { qa: 'специалист КК', operator: 'оператор', reviewer: 'проверяющий' };

const stored = load('cqa.role');
if (stored && stored in ROLES) S.role = stored;

export function setRole(role: Role) {
  S.role = role;
  save('cqa.role', role);
  toast(`Роль: ${ROLE_LOWER[role]}.`);
}

/** Домашний экран роли: только для пустого адреса. */
export const homeOf = (role: string) => (role === 'reviewer' ? '#/appeals' : '#/queue');

export type Theme = 'light' | 'dark';
export const systemTheme = (): Theme => (matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
export function applyTheme(theme: Theme, remember = false) {
  document.documentElement.dataset.theme = theme;
  if (remember) save('cqa.theme', theme);
  rerender();
}
export const currentTheme = (): Theme => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
