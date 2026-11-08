import { useEffect, useState } from 'react';
import { api } from '../lib/state.js';
import { Card, Chip, PageHead, Skeleton } from '../ui';

type CaseRow = {
  client_ref: string; contact_count: number; repeated_topic: string | null;
  status: string; priority: number; priority_reasons: { code: string; label: string }[];
  dialogs: { id: string; at: string; title: string | null; topic: string | null; status: string; risks: { label: string; basis: string }[]; evaluations: { criterion: string; a?: unknown; alt?: unknown }[]; reviewer_decisions: Record<string, unknown>[] }[];
};

export function CustomerCases() {
  const [rows, setRows] = useState<CaseRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get('/customer-cases').then(setRows).catch((e: Error) => setError(e.message));
  }, []);
  return (
    <div className="space-y-5">
      <PageHead title="Клиентские случаи" subtitle="Повторные обращения и прозрачная очередь проверки" />
      <p className="text-sm text-ink2">Связь выполняется только по псевдонимному ID, переданному банковской интеграцией. Имена и телефоны для сопоставления не используются. Приоритет — сигнал для проверки, а не прогноз ухода клиента.</p>
      {error && <Card className="p-4 text-risk">{error}</Card>}
      {!rows && !error && <Skeleton className="h-40" />}
      {rows?.length === 0 && <Card className="p-6 text-sm text-ink2">Нет связанных случаев. Проверьте, что источник передаёт стабильный client_ref.</Card>}
      {rows?.map(row => (
        <Card key={row.client_ref} className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="font-semibold">{row.client_ref}</h2><p className="text-sm text-ink2">{row.contact_count} обращений{row.repeated_topic ? ` · повторяется тема: ${row.repeated_topic}` : ''}</p></div>
            <Chip tone={row.priority >= 60 ? 'risk' : row.priority >= 30 ? 'ev' : 'info'}>Приоритет {row.priority}</Chip>
          </div>
          <div className="flex flex-wrap gap-2">{row.priority_reasons.map(reason => <Chip key={reason.code} tone="ev">{reason.label}</Chip>)}</div>
          <div className="divide-y divide-line">{row.dialogs.map(d => <div key={d.id} className="py-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2"><strong>{d.title || d.id}</strong><span className="text-ink2">{d.at} · {d.topic || 'Тема не определена'} · {d.status}</span></div>
            {d.risks.map((risk, n) => <p key={n} className="mt-1 text-risk">{risk.label}: {risk.basis}</p>)}
            {d.evaluations.length > 0 && <p className="mt-1 text-ink2">Оценки по критериям: {d.evaluations.map(e => String(e.criterion) + ': ' + String(e.a ?? '—')).join(' · ')}</p>}
            {d.reviewer_decisions.length > 0 && <p className="mt-1 text-ink2">Решения проверяющего: {d.reviewer_decisions.length}; откройте диалог для деталей.</p>}
          </div>)}</div>
        </Card>
      ))}
    </div>
  );
}
