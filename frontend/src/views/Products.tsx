// «Темы обращений» (GET/PUT /api/products): справочник тем, по которым модель определяет тему диалога.
// Сохраняется целиком; следующая оценка набора переопределит темы диалогов. Изменения видны до сохранения, отмена — одной кнопкой.
import { Plus, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { t } from '../lib/i18n.js';
import { api, toast } from '../lib/state.js';
import { useS } from '../store';
import { Button, Card, Field, PageHead, Skeleton, Tip } from '../ui';

type Topic = { id: string; name: string; description: string };
const ID = /^[a-z0-9-]{1,32}$/;

export function Products(_: { id: string | null }) {
  const S = useS();
  const qa = S.role === 'qa';
  const [saved, setSaved] = useState<Topic[] | null>(null);
  const [draft, setDraft] = useState<Topic[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    api.get('/products').then(
      (r: any) => {
        setSaved(r);
        setDraft(r.map((x: Topic) => ({ ...x })));
      },
      (e: any) => setErr(String(e?.message ?? e)),
    );
  }, []);

  const dirty = JSON.stringify(saved) !== JSON.stringify(draft);
  const ids = (draft ?? []).map(x => x.id);
  const problem = (x: Topic, i: number) =>
    !ID.test(x.id) ? t('Код: латиница, цифры и дефис, до 32 знаков') : ids.indexOf(x.id) !== i ? t('Такой код уже есть') : !x.name.trim() ? t('Название не может быть пустым') : '';
  const invalid = !draft?.length || draft.some((x, i) => problem(x, i));
  const set = (i: number, patch: Partial<Topic>) => setDraft(draft!.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const save = async () => {
    setBusy(true);
    try {
      const r: any = await api.put('/products', draft);
      setSaved(r);
      setDraft(r.map((x: Topic) => ({ ...x })));
      toast(t('Справочник тем сохранён. Темы диалогов обновятся при следующей оценке набора.'));
    } catch (e: any) {
      toast(t('Не сохранено: {e}', { e: e?.message ?? e }));
    }
    setBusy(false);
  };

  return (
    <>
      <PageHead title={t('Темы обращений')} sub={t('По этим темам модель определяет, о чём диалог; разрез «По продуктам» в аналитике строится по ним')}>
        {qa && dirty && (
          <Button variant="ghost" onClick={() => setDraft(saved!.map(x => ({ ...x })))} disabled={busy}>
            {t('Отменить')}
          </Button>
        )}
        {qa && (
          <Button variant="primary" onClick={save} disabled={busy || !dirty || invalid}>
            {busy ? t('Сохраняю…') : t('Сохранить')}
          </Button>
        )}
      </PageHead>
      {err && <p className="box risk">{err}</p>}
      {!draft && !err && <Skeleton className="h-64" />}
      {draft && (
        <Card>
          <ul className="divide-y divide-line2">
            {draft.map((x, i) => {
              const p = problem(x, i);
              return (
                <li key={i} className="grid gap-3 px-4 py-3.5 md:grid-cols-[160px_minmax(0,1fr)_minmax(0,1.6fr)_auto] md:items-start" data-topic={x.id}>
                  <Field label={t('Код')} hint={p && p.startsWith(t('Код')) ? p : undefined}>
                    <input className="fld" value={x.id} disabled={!qa || saved!.some(s => s.id === x.id && i < saved!.length)} onChange={e => set(i, { id: e.target.value.trim().toLowerCase() })} />
                  </Field>
                  <Field label={t('Название')}>
                    <input className="fld" value={x.name} disabled={!qa} onChange={e => set(i, { name: e.target.value })} />
                  </Field>
                  <Field label={t('Описание для модели')}>
                    <textarea className="fld min-h-[64px]" value={x.description ?? ''} disabled={!qa} onChange={e => set(i, { description: e.target.value })} />
                  </Field>
                  {qa && (
                    <Tip content={t('Удалить тему')}>
                      <Button variant="ghost" size="sm" className="md:mt-6" aria-label={t('Удалить тему')} onClick={() => setDraft(draft.filter((_, j) => j !== i))}>
                        <Trash2 size={16} aria-hidden="true" />
                      </Button>
                    </Tip>
                  )}
                  {p && !p.startsWith(t('Код')) && <p className="text-xs text-risk md:col-span-4">{p}</p>}
                </li>
              );
            })}
          </ul>
          {qa && (
            <div className="border-t border-line2 px-4 py-3">
              <Button onClick={() => setDraft([...draft, { id: '', name: '', description: '' }])}>
                <Plus size={16} aria-hidden="true" /> {t('Добавить тему')}
              </Button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
