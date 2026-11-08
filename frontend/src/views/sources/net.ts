// Запрос к API для «Источников» и «Автоматизации»: createApi не умеет DELETE и теряет ошибки по полям 422.
import { lang, t } from '../../lib/i18n.js';
import { api, userHeader } from '../../lib/state.js';

export type Fields = Record<string, string>;
export type Fail = Error & { status?: number; fields?: Fields };

/** Ошибки по полям: `{fields: {"config.url": "…"}}` или `{detail: [{loc: ["body", "evaluate", "batch_size"], msg}]}`. */
export const fieldsOf = (data: any): Fields =>
  data?.fields ??
  (Array.isArray(data?.detail)
    ? Object.fromEntries(data.detail.map((e: any) => [(e.loc ?? []).filter((p: unknown) => p !== 'body').join('.'), e.msg]))
    : {});

export async function send(method: string, path: string, body?: unknown): Promise<any> {
  const headers: Record<string, string> = { ...userHeader() };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(api.base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data: any = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* тело не JSON */
  }
  if (!res.ok) {
    const fields = fieldsOf(data);
    const detail = typeof data?.detail === 'string' ? data.detail : Object.keys(fields).length ? t('Проверьте поля формы') : text || res.statusText;
    throw Object.assign(new Error(detail), { status: res.status, fields }) as Fail;
  }
  return data;
}

/** «2026-11-08T06:20:00+05:00» → «08.11 06:20»: время сервера как есть. */
export const when = (at: string | null | undefined) => {
  const m = /^\d{4}-(\d\d)-(\d\d)[T ](\d\d:\d\d)/.exec(at ?? '');
  return m ? `${m[2]}.${m[1]} ${m[3]}` : at || '—';
};

/** Секунды → «5 мин», «3 ч», «2 дн». */
export const ago = (s: number | null | undefined) =>
  s == null ? '—' : s < 3600 ? t('{n} мин назад', { n: Math.max(1, Math.round(s / 60)) }) : s < 86400 ? t('{n} ч назад', { n: Math.round(s / 3600) }) : t('{n} дн назад', { n: Math.round(s / 86400) });

export const usd = (x: number | null | undefined) => (x == null ? '—' : `$${x.toLocaleString(lang === 'en' ? 'en-US' : 'ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
