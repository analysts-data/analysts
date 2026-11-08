// Перевод интерфейса: ключ — русский текст как он написан в коде, словари en и kk (frontend/src/i18n/*.json).
// {name} — подстановка. Данные не переводятся: названия критериев, реплики, обоснования модели.
let dict = null; // null — русский, исходные строки
export let lang = 'ru';

export function setDict(l, d) {
  lang = l;
  dict = l === 'ru' ? null : d;
}

export function t(ru, vars) {
  let s = (dict && dict[ru]) || ru;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  return s;
}
