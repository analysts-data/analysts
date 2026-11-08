// Сотрудники и алерты для шапки: список «Вы вошли как» и число новых алертов (колокольчик), опрос раз в 30 с.
// Формы ответов — design/contract.md (сотрудники, алерты).
import { useEffect } from 'react';
import { api } from './lib/state.js';
import { rerender, S } from './store';

/** Новые алерты: ответ — массив или объект со списком и счётчиками. */
export const newAlerts = (data: any): number =>
  data == null ? 0 : Array.isArray(data) ? data.filter((a: any) => a.status === 'new').length : (data.counts?.new ?? (data.items ?? []).filter((a: any) => a.status === 'new').length);

// Только то, что сервер объявил в features (GET /api/config): иначе 404 в консоли на старом сервере.
const has = (f: string) => !!S.features?.includes(f);

async function loadOps() {
  if (!has('employees') && !has('alerts')) return;
  const [emp, alerts] = await Promise.allSettled([has('employees') ? api.get('/employees') : null, has('alerts') ? api.get('/alerts?status=new') : null]);
  if (emp.status === 'fulfilled') S.employees = Array.isArray(emp.value) ? emp.value : emp.value?.items ?? [];
  if (alerts.status === 'fulfilled') S.alertsNew = newAlerts(alerts.value);
  rerender();
}

export function useOps() {
  const key = (S.features ?? []).join();
  useEffect(() => {
    loadOps();
    const t = setInterval(loadOps, 30_000);
    return () => clearInterval(t);
  }, [key]);
}

export const refreshOps = loadOps;
