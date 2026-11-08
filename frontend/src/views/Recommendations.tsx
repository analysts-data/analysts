// «Рекомендации» (GET /api/recommendations?for=operator|manager|checklist): явные правила сервера без модели.
// Каждый пункт — что сделать, почему одним предложением, правило, числа и диалоги-доказательства; при малой выборке —
// строка «недостаточно данных». Загружается по кнопке: интерфейс не строит догадок, показывает обоснование сервера.
import { useState } from 'react';
import { href } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { api } from '../lib/state.js';
import { Button, Card } from '../ui';

type For = 'operator' | 'manager' | 'checklist';

const numbers = (n: any) =>
  n && typeof n === 'object'
    ? Object.entries(n)
        .filter(([, v]) => v != null && typeof v !== 'object')
        .map(([k, v]) => `${k}: ${typeof v === 'number' ? (v as number).toLocaleString(undefined, { maximumFractionDigits: 2 }) : v}`)
        .join(' · ')
    : '';

function Item({ x }: { x: any }) {
  const [open, setOpen] = useState(false);
  const title = x.title ?? x.name ?? x.tag ?? x.cid;
  return (
    <li className="flex flex-col gap-1 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-ink">{title}</span>
        {x.basis && (
          <button type="button" className="text-xs font-semibold text-accent hover:text-accent-ink" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? t('Скрыть основание') : t('Почему')}
          </button>
        )}
      </div>
      {x.why && <p className="text-[13px] text-ink2">{x.why}</p>}
      {open && x.basis && (
        <div className="flex flex-col gap-1 rounded-lg bg-sunken px-3 py-2 text-xs text-ink2">
          {x.basis.rule && <p>{t('Правило: {rule}', { rule: x.basis.rule })}</p>}
          {numbers(x.basis.numbers) && <p className="tabular">{numbers(x.basis.numbers)}</p>}
          {x.basis.dialogs?.length > 0 && (
            <p className="flex flex-wrap gap-x-3 gap-y-1">
              {x.basis.dialogs.map((d: any) => (
                <a key={`${d.id}-${d.cid ?? ''}`} href={href('d', d.id)}>
                  {d.id}
                  {d.lines?.length ? `, ${t('реплики {n}', { n: d.lines.join(', ') })}` : ''}
                </a>
              ))}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function Recommendations({ kind, id, title }: { kind: For; id?: string; title?: string }) {
  const [st, setSt] = useState<{ busy?: boolean; data?: any; err?: string }>({});
  const load = async () => {
    setSt({ busy: true });
    try {
      const q = `/recommendations?for=${kind}${id ? `&id=${encodeURIComponent(id)}` : ''}`;
      setSt({ data: await api.get(q) });
    } catch (e: any) {
      setSt({ err: e?.status === 404 ? t('У сотрудника пока нет оценённых диалогов.') : String(e?.message ?? e) });
    }
  };
  const d = st.data;
  const items: any[] = d ? [...(d.items ?? []), ...(d.actions ?? []), ...(d.operators ?? []).map((o: any) => ({ ...o, title: o.title ?? o.operator }))] : [];
  return (
    <Card className="flex flex-col gap-2 px-4 py-3.5" data-recommendations={kind}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-semibold">{title ?? t('Рекомендации')}</h2>
          <p className="text-xs text-muted">{t('Явные правила по оценкам, без модели: у каждой рекомендации есть правило, числа и диалоги-доказательства.')}</p>
        </div>
        {!d && (
          <Button size="sm" onClick={load} disabled={st.busy}>
            {st.busy ? t('Загружаю…') : t('Показать рекомендации')}
          </Button>
        )}
      </div>
      {st.err && <p className="box ev">{st.err}</p>}
      {d && (
        <>
          {d.strength && <p className="text-[13px] text-ink2">{t('Сильная сторона: {name}', { name: d.strength.name ?? d.strength.title ?? d.strength.cid })}</p>}
          {items.length ? (
            <ul className="divide-y divide-line2">
              {items.map((x, i) => (
                <Item key={i} x={x} />
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted">{t('Правила не сработали: по этим данным рекомендаций нет.')}</p>
          )}
          {d.insufficient?.length > 0 && (
            <ul className="flex flex-col gap-0.5 text-xs text-muted">
              {d.insufficient.map((x: any, i: number) => (
                <li key={i}>
                  {x.subject ? `${x.subject}: ` : ''}
                  {x.text}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
