// Сотрудники и алерты для шапки: список «Вы вошли как» и число новых алертов (колокольчик), опрос раз в 30 с.
// Формы ответов — design/contract.md (сотрудники, алерты).
import { useEffect } from 'react';
import { api } from './lib/state.js';
import { rerender, S } from './store';

/** Новые алерты: ответ — массив или объект со списком и счётчиками. */
export const newAlerts = (data: any): number =>
  data == null ? 0 : Array.isArray(data) ? data.filter((a: any) => a.status === 'new').length : (data.counts?.new ?? (data.items ?? []).filter((a: any) => a.status === 'new').length);

async function loadOps() {
  const [emp, alerts] = await Promise.allSettled([api.get('/employees'), api.get('/alerts?status=new')]);
  if (emp.status === 'fulfilled') S.employees = Array.isArray(emp.value) ? emp.value : emp.value?.items ?? [];
  if (alerts.status === 'fulfilled') S.alertsNew = newAlerts(alerts.value);
  rerender();
}

export function useOps() {
  useEffect(() => {
    loadOps();
    const t = setInterval(loadOps, 30_000);
    return () => clearInterval(t);
  }, []);
}

export const refreshOps = loadOps;
