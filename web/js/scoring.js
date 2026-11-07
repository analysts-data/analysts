// Единственная реализация итога (design/contract.md «Итог», design/ports.md «Интерфейс»). Без DOM.

// Шум двоичной записи снимается toPrecision(12): 100 * 2.3 / 80 = 2.8749999999999996 → 2.88.
export const r2 = x => Math.round(Number((x * 100).toPrecision(12))) / 100;

const maxOf = c => Math.max(...c.steps);

export function frac(c, a) {
  if (a == null || a === 'na') return null;
  if (c.type === 'bool') return a === 'yes' ? 1 : 0;
  if (c.type === 'scale') return a / maxOf(c);
  return null;
}

// Последнее решение пары (appeal или review) со статусом confirmed или changed, как lastDec прототипа.
export const lastDec = (dialog, cid, appeals) =>
  appeals.filter(x => x.dlg === dialog.id && x.cid === cid && (x.status === 'changed' || x.status === 'confirmed')).at(-1);

export function ans(dialog, cid, appeals) {
  const r = dialog.res[cid];
  if (!r) return null;
  const dec = lastDec(dialog, cid, appeals);
  return dec ? dec.to : r.a;
}

// Итог = 100 × Σ(вес × доля) / Σ(вес применимых). N/A и критерии без записи исключаются, флаги не входят.
export function calc(dialog, checklist, appeals, override = null) {
  let W = 0, G = 0, pending = 0;
  const rows = [];
  for (const c of checklist.criteria) {
    if (c.type === 'flag') continue;
    const a = override && override.cid === c.id ? override.val : ans(dialog, c.id, appeals);
    if (a == null) { pending++; continue; }
    const f = frac(c, a);
    if (f == null) continue;
    W += c.w; G += c.w * f; rows.push({ c, a, f });
  }
  for (const r of rows) r.loss = W ? (100 * r.c.w * (1 - r.f)) / W : 0;
  const secs = checklist.sections.map((name, i) => {
    const rs = rows.filter(r => r.c.sec === i);
    return { name, n: rs.length, w: rs.reduce((s, r) => s + r.c.w, 0), g: rs.reduce((s, r) => s + r.c.w * r.f, 0) };
  }).filter(s => s.n);
  const losses = rows.filter(r => r.loss > 0).sort((x, y) => y.loss - x.loss);
  return { total: W ? r2((100 * G) / W) : null, W, G, pending, rows, secs, losses };
}

export function flagsOf(dialog, checklist) {
  const out = [];
  for (const fc of checklist.criteria) {
    if (fc.type !== 'flag') continue;
    const r = dialog.res[fc.id];
    if (r && r.a) for (const q of fc.questions || []) if (r.a[q.k]) out.push(q.label);
  }
  return out;
}
