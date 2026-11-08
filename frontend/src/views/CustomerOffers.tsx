import { useEffect, useState } from 'react';
import { t } from '../lib/i18n.js';
import { api, toast } from '../lib/state.js';
import { useS } from '../store';
import { Button, Card, PageHead, Skeleton } from '../ui';

type Offer = {
  id: string; name: string; description: string; topic_ids: string[]; keywords: string[];
  next_step: string; eligibility: string; approved: boolean;
};
type Topic = { id: string; name: string };
const ID = /^[a-z0-9-]{1,32}$/;
const split = (value: string) => value.split(',').map(x => x.trim()).filter(Boolean);

export function CustomerOffers(_: { id: string | null }) {
  const qa = useS().role === 'qa';
  const [saved, setSaved] = useState<Offer[] | null>(null);
  const [draft, setDraft] = useState<Offer[] | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    Promise.all([api.get('/customer-offers'), api.get('/products')]).then(([offers, catalog]: any[]) => {
      const normalized = offers.map((x: Offer) => ({ ...x, topic_ids: [...x.topic_ids], keywords: [...x.keywords] }));
      setSaved(normalized); setDraft(normalized.map((x: Offer) => ({ ...x, topic_ids: [...x.topic_ids], keywords: [...x.keywords] })));
      setTopics(catalog);
    }).catch((e: Error) => setError(e.message));
  }, []);
  const dirty = JSON.stringify(saved) !== JSON.stringify(draft);
  const invalid = !draft || draft.some((x, i) => !ID.test(x.id) || !x.name.trim() || draft.findIndex(y => y.id === x.id) !== i || (x.approved && !x.topic_ids.length && !x.keywords.length));
  const update = (index: number, patch: Partial<Offer>) => setDraft(draft!.map((x, i) => i === index ? { ...x, ...patch } : x));
  const save = async () => {
    setBusy(true);
    try {
      const result: any = await api.put('/customer-offers', draft);
      const normalized = result.map((x: Offer) => ({ ...x, topic_ids: [...x.topic_ids], keywords: [...x.keywords] }));
      setSaved(normalized); setDraft(normalized);
      toast(t('Каталог решений сохранён.'));
    } catch (e: any) { toast(t('Не сохранено: {e}', { e: e?.message ?? e })); }
    finally { setBusy(false); }
  };
  const add = () => {
    const id = 'offer-' + Date.now().toString(36);
    const item: Offer = { id, name: '', description: '', topic_ids: [], keywords: [], next_step: '', eligibility: '', approved: false };
    setDraft([...(draft ?? []), item]);
  };
  return (
    <div className="space-y-5">
      <PageHead title={t('Каталог решений')} sub={t('Одобренные предложения и прозрачные правила сопоставления с темами или фразами клиента')}>
        {qa && <Button variant="ghost" onClick={add} disabled={busy}>{t('Добавить предложение')}</Button>}
        {qa && <Button variant="primary" onClick={save} disabled={busy || !dirty || invalid}>{busy ? t('Сохраняю…') : t('Сохранить')}</Button>}
      </PageHead>
      <p className="text-sm text-ink2">{t('Каталог тем классифицирует обращения и не является каталогом банковских продуктов. Здесь задаются только предложения, проверенные банком. Для рекомендации требуется точное совпадение с темой или ключевой фразой. Сотрудник проверяет условия и уместность до контакта.')}</p>
      {error && <Card className="p-4 text-risk">{error}</Card>}
      {!draft && !error && <Skeleton className="h-40" />}
      {draft?.length === 0 && <Card className="p-5 text-sm text-ink2">{t('Пока нет предложений. Добавьте предложение, правила сопоставления и одобрите его.')}</Card>}
      {draft?.map((offer, i) => (
        <Card key={offer.id} className="space-y-4 p-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm">{t('Код')}<input className="fld mt-1" value={offer.id} disabled={!qa || saved?.some(x => x.id === offer.id)} onChange={e => update(i, { id: e.target.value })} /></label>
            <label className="text-sm">{t('Название предложения')}<input className="fld mt-1" value={offer.name} disabled={!qa} onChange={e => update(i, { name: e.target.value })} /></label>
            <label className="text-sm md:col-span-2">{t('Описание решения')}<textarea className="fld mt-1 min-h-20" value={offer.description} disabled={!qa} onChange={e => update(i, { description: e.target.value })} /></label>
            <label className="text-sm md:col-span-2">{t('Коды тем через запятую')}<input className="fld mt-1" value={offer.topic_ids.join(', ')} disabled={!qa} placeholder={topics.map(x => x.id).join(', ')} onChange={e => update(i, { topic_ids: split(e.target.value) })} /><span className="mt-1 block text-xs text-ink2">{t('Доступные темы: {topics}', { topics: topics.map(x => x.id + ' — ' + x.name).join('; ') || '—' })}</span></label>
            <label className="text-sm md:col-span-2">{t('Ключевые фразы на русском, казахском или английском через запятую')}<input className="fld mt-1" value={offer.keywords.join(', ')} disabled={!qa} onChange={e => update(i, { keywords: split(e.target.value) })} /></label>
            <label className="text-sm">{t('Следующий шаг сотрудника')}<textarea className="fld mt-1 min-h-16" value={offer.next_step} disabled={!qa} onChange={e => update(i, { next_step: e.target.value })} /></label>
            <label className="text-sm">{t('Что проверить по условиям')}<textarea className="fld mt-1 min-h-16" value={offer.eligibility} disabled={!qa} onChange={e => update(i, { eligibility: e.target.value })} /></label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={offer.approved} disabled={!qa} onChange={e => update(i, { approved: e.target.checked })} />{t('Одобрено банком и доступно для подсказок')}</label>
            {qa && <Button variant="ghost" onClick={() => setDraft(draft!.filter((_, j) => j !== i))}>{t('Удалить')}</Button>}
          </div>
          {offer.approved && !offer.topic_ids.length && !offer.keywords.length && <p className="text-sm text-risk">{t('Добавьте хотя бы одно правило сопоставления.')}</p>}
        </Card>
      ))}
      {qa && invalid && draft?.length ? <p className="text-sm text-risk">{t('Проверьте уникальность кода, название и правила для одобренных предложений.')}</p> : null}
    </div>
  );
}
