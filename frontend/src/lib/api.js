// Клиент API по design/contract.md. Базовый адрес: параметр data страницы, атрибут data-api, иначе /api.
export const resolveBase = (search, attr) => new URLSearchParams(search).get('data') || attr || '/api';

// headers — заголовки каждого запроса (X-CQA-User выбранного сотрудника), функция: выбор меняется без пересоздания клиента.
// after(method, path, body) — после успешного ответа (метрики использования).
export function createApi(base, fetchFn = globalThis.fetch.bind(globalThis), headers = () => ({}), after = () => {}) {
  // send — тело ответа текстом (Markdown разницы версий), call — JSON
  const send = async (method, path, body, raw = false) => {
    const init = { method };
    const extra = headers();
    if (Object.keys(extra).length) init.headers = { ...extra };
    if (body !== undefined) {
      init.headers = { ...init.headers, 'Content-Type': 'application/json' };
      init.body = raw ? body : JSON.stringify(body);
    }
    const res = await fetchFn(base + path, init);
    const text = await res.text();
    if (!res.ok) {
      let detail = text, body = null;
      try { body = JSON.parse(text); detail = body.detail ?? text; } catch { /* тело не JSON */ }
      if (typeof detail !== 'string') detail = JSON.stringify(detail);
      // body — разобранный ответ ошибки: формы показывают ошибки у полей (fields, detail[].loc)
      throw Object.assign(new Error(`${res.status}: ${detail}`), { status: res.status, body });
    }
    after(method, path, raw ? undefined : body);
    return text;
  };
  const call = async (...args) => {
    const text = await send(...args);
    return text ? JSON.parse(text) : null;
  };
  const id = encodeURIComponent;
  return {
    base,
    // Новые разделы (сотрудники, алерты, маркеры, продукты, журнал): пути — design/contract.md.
    get: path => call('GET', path),
    post: (path, body) => call('POST', path, body),
    put: (path, body) => call('PUT', path, body),
    del: path => call('DELETE', path),
    getState: () => call('GET', '/state'),
    postDataset: groupId => call('POST', '/datasets', { group_id: groupId }),
    uploadDataset: file => call('POST', '/datasets/upload', file, true),
    postPaste: payload => call('POST', '/dialogs/text', payload),
    postRun: ({ dialogs, criteria }) => call('POST', '/runs', { dialogs, criteria }),
    getRun: rid => call('GET', `/runs/${id(rid)}`),
    cancelRun: rid => call('POST', `/runs/${id(rid)}/cancel`),
    putChecklist: draft => call('PUT', '/checklist', draft),
    postAppeal: payload => call('POST', '/appeals', payload),
    postDecision: (aid, payload) => call('POST', `/appeals/${id(aid)}/decision`, payload),
    postReview: payload => call('POST', '/decisions', payload),
    postReviewed: (did, reviewed) => call('POST', `/dialogs/${id(did)}/reviewed`, { reviewed }),
    putOwners: owners => call('PUT', '/owners', owners),
    putSource: (url, groupId) => call('PUT', '/source', { url, group_id: groupId }),
    putAnswer: (did, cid, payload) => call('PUT', `/dialogs/${id(did)}/answers/${id(cid)}`, payload),
    getConfig: () => call('GET', '/config'),
    putConfig: cfg => call('PUT', '/config', cfg),
    putProvider: (pid, provider) => call('PUT', `/providers/${id(pid)}`, provider),
    deleteProvider: pid => call('DELETE', `/providers/${id(pid)}`),
    checkProvider: pid => call('POST', `/providers/${id(pid)}/check`),
    diffVersions: (from, to) => send('GET', `/checklist/diff?from=${id(from)}&to=${id(to)}&format=md`),
    diffDraft: draft => send('POST', '/checklist/diff?format=md', draft),
    exportUrl: (v, fmt) => `${base}/checklist/export?v=${id(v)}&format=${id(fmt)}`,
    getProsody: did => call('GET', `/dialogs/${id(did)}/prosody`),
    audioUrl: did => `${base}/dialogs/${id(did)}/audio`,
    playerUrl: did => `${base}/dialogs/${id(did)}/player`,
  };
}
