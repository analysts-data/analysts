// Данные новых экранов (сотрудники, журнал, использование, отчёты, прогоны): GET с загрузкой и ошибкой,
// выгрузка файла со статусом «Готовится файл…», сырое тело CSV. Пути — design/contract.md.
import { useEffect, useState } from 'react';
import { t } from '../../lib/i18n.js';
import { api, toast, userHeader } from '../../lib/state.js';
import { track } from '../../lib/telemetry.js';
import { Button } from '../../ui';

/** GET {api}{path}; path null — не запрашивать. reload() повторяет запрос. */
export function useGet<T = any>(path: string | null) {
  const [s, set] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: !!path });
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!path) return;
    let live = true;
    set(x => ({ ...x, loading: true, error: null }));
    api.get(path).then(
      (data: T) => live && set({ data, error: null, loading: false }),
      (e: Error) => live && set({ data: null, error: e.message, loading: false }),
    );
    return () => {
      live = false;
    };
  }, [path, n]);
  return { ...s, reload: () => setN(x => x + 1) };
}

/** Список из ответа: массив или объект {items} (у /api/operators — {operators}). */
export const listOf = (data: any): any[] => (Array.isArray(data) ? data : data?.items ?? data?.operators ?? []);

/** Путь шаблона сервера «/api/…» → адрес от текущей базы API (параметр ?data= и data-api тоже работают). */
export const apiUrl = (path: string) => api.base + path.replace(/^\/api(?=\/)/, '');

/** POST сырым телом (CSV): createApi шлёт только JSON. */
export async function postRaw(path: string, text: string) {
  const res = await fetch(apiUrl(path), { method: 'POST', headers: { ...userHeader(), 'Content-Type': 'text/csv; charset=utf-8' }, body: text });
  const body = await res.text();
  if (!res.ok) {
    let detail = body;
    try {
      detail = JSON.parse(body).detail ?? body;
    } catch {
      /* тело не JSON */
    }
    throw new Error(`${res.status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  return body ? JSON.parse(body) : null;
}

// fetch, а не ссылка: запрос несёт X-CQA-User, выгрузка попадает в журнал с именем сотрудника.
async function download(path: string, name: string) {
  const res = await fetch(apiUrl(path), { headers: userHeader() });
  if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 200)}`);
  const file = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? name;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await res.blob());
  a.download = file;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** Кнопка выгрузки: пока сервер готовит файл, неактивна и пишет «Готовится файл…». */
export function DownloadButton({ path, name, kind, children, variant }: { path: string; name: string; kind: string; children: React.ReactNode; variant?: 'default' | 'ghost' }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant={variant}
      data-act="download"
      data-kind={kind}
      disabled={busy}
      aria-busy={busy}
      onClick={async () => {
        setBusy(true);
        track('export', { kind });
        try {
          await download(path, name);
        } catch (e) {
          toast(t('Файл не выгружен: {error}', { error: e.message }));
        }
        setBusy(false);
      }}
    >
      {busy ? t('Готовится файл…') : children}
    </Button>
  );
}

/** «2026-11-08T06:20:00+05:00» → «08.11 06:20»: время сервера (Астана) как есть, без пересчёта в пояс браузера. */
export const when = (at: string | null | undefined) => {
  const m = /^\d{4}-(\d\d)-(\d\d)[T ](\d\d:\d\d)/.exec(at ?? '');
  return m ? `${m[2]}.${m[1]} ${m[3]}` : at || '—';
};

export const pct = (x: number | null | undefined) => (x == null ? '—' : `${Math.round(100 * x)}%`);

// Подписи — функции: язык меняется без перезагрузки, t() должен вызываться при отрисовке.
export const roleNames = (): Record<string, string> => ({
  operator: t('Оператор'),
  qa: t('Специалист КК'),
  reviewer: t('Проверяющий'),
  manager: t('Руководитель'),
  admin: t('Администратор'),
});
export const ROLES = Object.keys(roleNames());
export const roleName = (r: string) => roleNames()[r] ?? r;

// Действия журнала (src/cqa/services/audit.py); неизвестный код показывается как есть.
export const actionNames = (): Record<string, string> => ({
  'appeal.file': t('Подал апелляцию'),
  'appeal.decide': t('Решил апелляцию'),
  'review.decide': t('Решил расхождение моделей'),
  'answer.manual': t('Исправил оценку'),
  'dialog.reviewed': t('Отметил диалог проверенным'),
  'checklist.save': t('Сохранил чек-лист'),
  'dataset.upload': t('Загрузил набор'),
  'dataset.paste': t('Добавил диалог текстом'),
  'owners.save': t('Назначил, кто исправляет'),
  'provider.save': t('Изменил провайдера модели'),
  'config.save': t('Изменил режим оценки'),
  'employee.import': t('Импортировал сотрудников'),
  'employee.save': t('Изменил сотрудника'),
  'operator.import': t('Импортировал операторов диалогов'),
  'operator.assign': t('Назначил оператора диалогу'),
  'run.start': t('Запустил оценку'),
  'run.cancel': t('Остановил оценку'),
  'result.restore': t('Вернул прежнюю оценку'),
  'alert.ack': t('Принял алерт'),
  'alert.resolve': t('Решил алерт'),
  'marker.save': t('Изменил маркеры'),
  'product.save': t('Исправил продукт'),
  export: t('Выгрузил файл'),
});
export const actionName = (a: string) => actionNames()[a] ?? a;
