// «Почему» у вычисленного значения (флаг, маркер, продукт, интонация): по клику окно с полем basis от сервера как есть.
// Правило, порог, наблюдённое значение, вероятности и реплики-основания; своих догадок интерфейс не добавляет.
import { useState } from 'react';
import { fn } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { Button, cn, Modal } from '../../ui';
import { lineBy } from './util';

const LABEL: Record<string, () => string> = {
  rule: () => t('Правило'),
  why: () => t('Обоснование'),
  reason: () => t('Обоснование'),
  threshold: () => t('Порог'),
  threshold_why: () => t('Почему такой порог'),
  value: () => t('Наблюдённое значение'),
  observed: () => t('Наблюдённое значение'),
  confidence: () => t('Уверенность'),
  by: () => t('Кто определил'),
};
const val = (v: any) => (typeof v === 'number' ? fn(v) : typeof v === 'boolean' ? (v ? t('да') : t('нет')) : String(v));

export function WhyBody({ basis, d, onLine }: { basis: any; d: any; onLine?: (n: number) => void }) {
  if (typeof basis === 'string') return <p className="text-sm">{basis}</p>;
  const rows = Object.entries(basis || {}).filter(([k, v]) => k !== 'ev' && k !== 'probs' && v != null && v !== '' && typeof v !== 'object');
  const probs = basis?.probs ? Object.entries(basis.probs as Record<string, number>).sort((a, b) => b[1] - a[1]) : [];
  const ev: number[] = Array.isArray(basis?.ev) ? basis.ev : [];
  return (
    <div className="flex flex-col gap-3 text-sm" data-why="body">
      {rows.length > 0 && (
        <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{LABEL[k]?.() ?? k}</dt>
              <dd className="m-0">{val(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {probs.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold text-ink2">{t('Вероятности')}</span>
          <table className="tbl text-[13px]">
            <tbody>
              {probs.map(([k, p]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td className="num text-right">{fn(p)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {ev.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink2">{t('Реплики')}</span>
          {ev.map(n => {
            const l = d && lineBy(d, n);
            return (
              <div key={n} className="flex flex-wrap items-start justify-between gap-2 border-l-2 border-ev pl-3 text-[13px]">
                <span className="min-w-0 flex-1">
                  <span className="text-xs text-muted">{t('Реплика {n}', { n })}</span>
                  {l && (
                    <>
                      <br />«{l.text}»
                    </>
                  )}
                </span>
                {l && onLine && (
                  <Button size="sm" data-act="whyline" onClick={() => onLine(n)}>
                    {t('К реплике')}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      )}
      {!rows.length && !probs.length && !ev.length && <p className="text-muted">{t('Сервер не передал обоснование.')}</p>}
    </div>
  );
}

/** Кнопка (по умолчанию «Почему») и окно с обоснованием. Без basis кнопки нет. */
export function Why({ title, basis, d, onLine, className, children, label }: { title: string; basis: any; d: any; onLine?: (n: number) => void; className?: string; children?: React.ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  if (basis == null) return <>{children}</>;
  return (
    <>
      <button
        type="button"
        data-act="why"
        aria-label={label}
        className={cn(children ? 'cursor-pointer' : 'text-[13px] font-semibold text-accent hover:underline', className)}
        onClick={() => setOpen(true)}
      >
        {children ?? t('Почему')}
      </button>
      <Modal open={open} onOpenChange={setOpen} title={title} description={t('Обоснование, которое передал сервер.')}>
        <WhyBody
          basis={basis}
          d={d}
          onLine={
            onLine &&
            (n => {
              setOpen(false);
              onLine(n);
            })
          }
        />
      </Modal>
    </>
  );
}
