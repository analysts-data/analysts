// Состояние приложения: данные GET /api/state как есть и состояние интерфейса. Группа 3 добавит api и действия.
export const S = {
  base: '/api', r: null, loading: true, error: null,
  checklist: null, versions: [], dialogs: [], appeals: [], owners: {}, mode: null,
  role: 'qa', q: '', open: {},
};

export const render = focus => S.app?.render(focus);

export async function reload() {
  try {
    const res = await fetch(`${S.base}/state`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    Object.assign(S, await res.json(), { error: null });
  } catch (e) {
    S.error = e.message || String(e);
  }
  S.loading = false;
  render();
}

let toastT;
export function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => { t.hidden = true; }, 5200);
}
