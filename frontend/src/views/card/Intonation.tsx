// Интонация звонка по звуку (GET /api/dialogs/{id}/prosody): один запрос на звонок, ответ кешируется на сессию.
import { useEffect, useState } from 'react';
import { api } from '../../lib/state.js';
import { Chip } from '../../ui';

// id → 'loading' | ответ сервера | {off: true} (запись не получена) | null (записи нет: панели нет)
const cache: Record<string, any> = {};
const BADGE: Record<string, string> = { raised: '↑ тон', monotone: 'монотонно', fast: 'быстро', overlap: 'перебивание' };

export function useProsody(d: any) {
  const on = Boolean(d && d.ch === 'call' && d.lines);
  const [, force] = useState(0);
  useEffect(() => {
    if (!on || d.id in cache) return;
    cache[d.id] = 'loading';
    api
      .getProsody(d.id)
      .then(
        (p: any) => (cache[d.id] = p),
        (e: any) => (cache[d.id] = e.status === 404 ? null : { off: true }),
      )
      .then(() => force(x => x + 1));
  }, [on, d?.id]);
  return on ? cache[d.id] : null;
}

export function IntonationPanel({ p }: { p: any }) {
  if (!p) return null;
  if (p === 'loading')
    return (
      <p className="text-xs text-muted" data-prosody="loading">
        Интонация: разбираем запись…
      </p>
    );
  if (p.off)
    return (
      <p className="text-xs text-muted" data-prosody="off">
        Интонация недоступна: запись не загрузилась.
      </p>
    );
  return (
    <section className="flex flex-col gap-1.5 rounded-card border border-line bg-surface p-4 shadow-card" data-prosody="on" aria-label="Интонация">
      <h2 className="text-[15px] font-semibold">Интонация</h2>
      {p.summary.length ? (
        <ul className="m-0 list-disc pl-5 text-[13px]">
          {p.summary.map((s: string, i: number) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px]">Тон, громкость и темп в обычной манере говорящих, долгих пауз перед ответом нет.</p>
      )}
      <p className="text-xs text-muted">По звуку записи: реплика сравнивается с обычной манерой того же говорящего. Пороги эвристические, на итог не влияют.</p>
    </section>
  );
}

/** Метки интонации у реплики n. */
export function ProsodyBadges({ p, n }: { p: any; n: number }) {
  const l = p && p.lines ? p.lines.find((x: any) => x.n === n) : null;
  if (!l) return null;
  return l.flags.map((f: string) => (
    <Chip key={f} tone="info" className="pros" title="Интонация по звуку записи">
      {f === 'long_pause' ? `пауза ${Math.round(l.pause)} с` : BADGE[f]}
    </Chip>
  ));
}
