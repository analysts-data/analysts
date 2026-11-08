// Интонация звонка по звуку (GET /api/dialogs/{id}/prosody): один запрос на звонок, ответ кешируется на сессию.
import { useEffect, useState } from 'react';
import { fn } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { api } from '../../lib/state.js';
import { Term } from '../../terms';
import { Chip } from '../../ui';
import { Why } from './Why';

// id → 'loading' | ответ сервера | {off: true} (запись не получена) | null (записи нет: панели нет)
const cache: Record<string, any> = {};
const BADGE: Record<string, () => string> = { raised: () => t('↑ тон'), monotone: () => t('монотонно'), fast: () => t('быстро'), overlap: () => t('перебивание') };

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
        {t('Интонация считается…')}
      </p>
    );
  if (p.off)
    return (
      <p className="text-xs text-muted" data-prosody="off">
        {t('Интонация недоступна: запись не загрузилась.')}
      </p>
    );
  return (
    <section className="flex flex-col gap-1.5 rounded-card border border-line bg-surface p-4 shadow-card" data-prosody="on" aria-label={t('Интонация')}>
      <h2 className="text-[15px] font-semibold">
        <Term k="prosody">{t('Интонация по записи')}</Term>
      </h2>
      {p.summary.length ? (
        <ul className="m-0 list-disc pl-5 text-[13px]">
          {p.summary.map((s: string, i: number) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px]">{t('Тон, громкость и темп в обычной манере говорящих, долгих пауз перед ответом нет.')}</p>
      )}
      <p className="text-xs text-muted">{t('↑ тон: громче и выше обычного · быстро: темп выше обычного · перебивание · пауза N с перед ответом')}</p>
      <p className="text-xs text-muted">{t('Реплика сравнивается с обычной манерой того же говорящего. Подсказка для прослушивания, на балл не влияет.')}</p>
    </section>
  );
}

// «Почему» у метки: basis сервера, если он есть, иначе измерения реплики рядом с обычной манерой говорящего из ответа.
function measured(l: any, sp: any) {
  const o: Record<string, string> = {};
  const add = (k: string, v: any, unit: string, norm?: any) => {
    if (v != null) o[k] = `${fn(v)} ${unit}` + (norm != null ? t(', обычно {norm}', { norm: fn(norm) }) : '');
  };
  add(t('Тон'), l.f0, t('Гц'), sp?.f0);
  add(t('Размах тона'), l.range_st, t('полутона'));
  add(t('Громкость'), l.db, t('дБ'), sp?.db);
  add(t('Темп'), l.wps, t('слов в секунду'), sp?.wps);
  add(t('Пауза перед репликой'), l.pause, t('с'));
  return o;
}

/** Метки интонации у реплики n; по клику — почему метка поставлена. */
export function ProsodyBadges({ p, n, who }: { p: any; n: number; who?: string }) {
  const l = p && p.lines ? p.lines.find((x: any) => x.n === n) : null;
  if (!l) return null;
  return l.flags.map((f: string) => {
    const text = f === 'long_pause' ? t('пауза {s} с', { s: Math.round(l.pause) }) : BADGE[f]?.() ?? f;
    return (
      <Why key={f} title={t('Почему «{text}» у реплики {n}', { text, n })} basis={l.basis ?? measured(l, who && p.speakers?.[who])} d={null} label={t('Почему: {text}', { text })}>
        <Chip tone="info" className="pros">
          {text}
        </Chip>
      </Why>
    );
  });
}
