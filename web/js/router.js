// Hash-роутинг: #/queue?grp=risk, #/d/{id}, #/appeals/{id}, #/checklist, #/analytics, #/coaching. Без DOM.
const PAGES = ['queue', 'd', 'appeals', 'checklist', 'analytics', 'coaching'];

export function parseHash(hash) {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const [page, id] = path.split('/');
  if (!PAGES.includes(page)) return { page: 'queue', id: null, params: {} };
  return { page, id: id ? decodeURIComponent(id) : null, params: Object.fromEntries(new URLSearchParams(query)) };
}

export function href(page, id = null, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  return `#/${page}${id ? '/' + encodeURIComponent(id) : ''}${q ? '?' + q : ''}`;
}
