import { useEffect, useState } from 'react';
import { api } from '../lib/state.js';
import { Card, Chip, PageHead, Skeleton } from '../ui';

type Evidence = { dialog_id: string; line: number; text: string; match: string };
type Offer = { id: string; name: string; description: string; next_step: string; eligibility: string };
type CaseRow = {
  client_ref: string; contact_count: number; repeated_topic: string | null; unresolved_count: number; resolved_count: number;
  client_request_signals: { phrase: string; offer_id: string }[];
  suggestions: { offer: Offer; basis: string[]; matched_topics: string[]; evidence: Evidence[] }[];
  status: string; priority: number; priority_reasons: { code: string; label: string }[];
  dialogs: { id: string; at: string; title: string | null; topic: string | null; status: string; risks: { label: string; basis: string }[]; evaluations: { criterion: string; a?: unknown; alt?: unknown }[]; reviewer_decisions: { status?: string; cid?: string; from?: unknown; to?: unknown; reason?: string; reviewer?: string }[] }[];
};
const STATUS: Record<string, string> = { unknown: 'Статус не указан', open: 'Не решено', in_progress: 'В работе', resolved: 'Решено' };

export function CustomerCases() {
  const [rows, setRows] = useState<CaseRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    setRows(null);
    api.get('/customer-cases').then(setRows).catch((e: Error) => setError(e.message));
  }, [reloadKey]);
  const updateStatus = async (id: string, status: string) => {
    setBusy(id);
    try {
      await api.put('/dialogs/' + encodeURIComponent(id) + '/case-status', { status });
      setReloadKey(x => x + 1);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  return (
    <div className="space-y-5">
      <PageHead title="Клиентские случаи" sub="Повторные обращения, решение проблемы и подходящие банковские предложения" />
      <p className="text-sm text-ink2">Связь выполняется только по псевдонимному ID из интеграции. Предложения подбираются по подтверждённой теме или ключевой фразе в реплике клиента и требуют предварительного одобрения в разделе «Каталог решений». Это подсказка сотруднику, не автоматическая продажа и не прогноз ухода клиента.</p>
      {error && <Card className="p-4 text-risk">{error}</Card>}
      {!rows && !error && <Skeleton className="h-40" />}
      {rows?.length === 0 && <Card className="p-6 text-sm text-ink2">Нет связанных случаев. Проверьте, что источник передаёт стабильный client_ref.</Card>}
      {rows?.map(row => (
        <Card key={row.client_ref} className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="font-semibold">{row.client_ref}</h2><p className="text-sm text-ink2">{row.contact_count} обращений{row.repeated_topic ? ' · повторяется тема: ' + row.repeated_topic : ''} · открыто: {row.unresolved_count} · решено: {row.resolved_count}</p></div>
            <Chip tone={row.priority >= 60 ? 'risk' : row.priority >= 30 ? 'ev' : 'info'}>Приоритет проверки {row.priority}</Chip>
          </div>
          <div className="flex flex-wrap gap-2">{row.priority_reasons.map(reason => <Chip key={reason.code} tone="ev">{reason.label}</Chip>)}</div>

          <section className="space-y-2">
            <h3 className="font-semibold">Запросы, явно отмеченные в репликах</h3>
            {row.client_request_signals.length ? <div className="flex flex-wrap gap-2">{row.client_request_signals.map((x, i) => <Chip key={x.offer_id + x.phrase + i} tone="info">{x.phrase}</Chip>)}</div> : <p className="text-sm text-ink2">Не найдено ключевых фраз из одобренного каталога. Автоматически приписывать клиенту пожелание не будем.</p>}
          </section>

          <section className="space-y-3">
            <h3 className="font-semibold">Возможные решения из одобренного каталога</h3>
            {row.suggestions.length === 0 && <p className="text-sm text-ink2">Подходящего подтверждённого предложения пока нет. Добавьте предложение и правила соответствия в «Каталог решений».</p>}
            {row.suggestions.map(({ offer, basis, matched_topics, evidence }) => (
              <div key={offer.id} className="rounded-lg border border-line p-4">
                <div className="font-semibold">{offer.name}</div>
                {offer.description && <p className="mt-1 text-sm">{offer.description}</p>}
                <p className="mt-2 text-sm text-ink2">Почему предложено: {basis.join('; ')}{matched_topics.length ? ' · темы: ' + matched_topics.join(', ') : ''}</p>
                {offer.next_step && <p className="mt-2 text-sm"><strong>Следующий шаг:</strong> {offer.next_step}</p>}
                {offer.eligibility && <p className="mt-1 text-sm"><strong>Проверить перед предложением:</strong> {offer.eligibility}</p>}
                {evidence.map((ev, i) => <blockquote key={ev.dialog_id + ev.line + i} className="mt-2 border-l-2 border-brand pl-3 text-sm text-ink2">Диалог {ev.dialog_id}, реплика {ev.line}: «{ev.text}» {ev.match ? '· совпадение: ' + ev.match : ''}</blockquote>)}
                <p className="mt-2 text-xs text-ink2">Сотрудник должен проверить уместность и условия до контакта с клиентом.</p>
              </div>
            ))}
          </section>

          <section className="space-y-2">
            <h3 className="font-semibold">История обращений</h3>
            <div className="divide-y divide-line">{row.dialogs.map(d => <div key={d.id} className="py-3 text-sm">
              <div className="flex flex-wrap justify-between gap-2"><strong>{d.title || d.id}</strong><span className="text-ink2">{d.at} · {d.topic || 'Тема не определена'}</span></div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <label className="text-ink2" htmlFor={'status-' + d.id}>Решение проблемы:</label>
                <select id={'status-' + d.id} className="rounded border border-line bg-panel px-2 py-1" value={d.status} disabled={busy === d.id} onChange={e => updateStatus(d.id, e.target.value)}>
                  {Object.entries(STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                {busy === d.id && <span className="text-ink2">Сохраняю…</span>}
              </div>
              {d.risks.map((risk, n) => <p key={n} className="mt-1 text-risk">{risk.label}: {risk.basis}</p>)}
              {d.evaluations.length > 0 && <p className="mt-1 text-ink2">Оценки по критериям: {d.evaluations.map(e => String(e.criterion) + ': ' + String(e.a ?? '—')).join(' · ')}</p>}
              {d.reviewer_decisions.map((decision, n) => <p key={n} className="mt-1 text-ink2">Проверка {decision.cid || ''}: {String(decision.from ?? '—')} → {String(decision.to ?? '—')} · {decision.status || 'без статуса'}{decision.reviewer ? ' · ' + decision.reviewer : ''}{decision.reason ? ' · ' + decision.reason : ''}</p>)}
            </div>)}</div>
          </section>
        </Card>
      ))}
    </div>
  );
}
