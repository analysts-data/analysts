// «Достаточность данных» (GET/PUT /api/sufficiency): что делать с диалогом, данных в котором мало для честной оценки.
// Исход каждого правила: «Недостаточно данных» (модели не отправляется), «Мало данных» (оценивается, но ждёт проверки
// человека) или «Только сведение». Обоснование исхода по умолчанию — от сервера (docs/insufficient-data.md).
import { useEffect, useState } from 'react';
import { msg, t } from '../lib/i18n.js';
import { api, reload, toast } from '../lib/state.js';
import { Button, Card, Chip, PageHead, Skeleton } from '../ui';

const OUTCOMES: [string, string][] = [
  ['block', msg('Недостаточно данных: модели не отправлять')],
  ['flag', msg('Мало данных: оценить и отправить на проверку')],
  ['info', msg('Только сведение')],
];

export function Sufficiency(_: { id: string | null }) {
  const [rules, setRules] = useState<any[] | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    api.get('/sufficiency').then(
      (r: any) => setRules(r.rules ?? []),
      (e: any) => setErr(String(e?.message ?? e)),
    );
  }, []);

  const changed = Object.keys(draft).filter(k => draft[k] !== rules?.find(r => r.id === k)?.outcome);
  const save = async () => {
    setBusy(true);
    try {
      const r: any = await api.put('/sufficiency', Object.fromEntries(changed.map(k => [k, draft[k]])));
      setRules(r.rules ?? []);
      setDraft({});
      toast(t('Правила достаточности данных сохранены. Статусы диалогов пересчитаны.'));
      await reload();
    } catch (e: any) {
      toast(t('Не сохранено: {e}', { e: e?.message ?? e }));
    }
    setBusy(false);
  };

  return (
    <>
      <PageHead title={t('Достаточность данных')} sub={t('Что делать с диалогом, в котором мало данных для честной оценки')}>
        <Button variant="primary" onClick={save} disabled={busy || !changed.length}>
          {busy ? t('Сохраняю…') : t('Сохранить')}
        </Button>
      </PageHead>
      {err && <p className="box risk">{err}</p>}
      {!rules && !err && <Skeleton className="h-64" />}
      {rules && (
        <Card>
          <ul className="divide-y divide-line2">
            {rules.map(r => {
              const value = draft[r.id] ?? r.outcome;
              return (
                <li key={r.id} className="grid gap-3 px-4 py-3.5 md:grid-cols-[minmax(0,1fr)_320px] md:items-center" data-rule={r.id}>
                  <div className="min-w-0">
                    <p className="font-semibold text-ink">{r.text}</p>
                    {r.why && <p className="text-[13px] text-muted">{r.why}</p>}
                  </div>
                  <div className="flex flex-col gap-1">
                    <select aria-label={t('Исход для правила «{text}»', { text: r.text })} value={value} onChange={e => setDraft({ ...draft, [r.id]: e.target.value })}>
                      {OUTCOMES.map(([k, label]) => (
                        <option key={k} value={k}>
                          {t(label)}
                        </option>
                      ))}
                    </select>
                    {value === r.default ? (
                      <span className="text-xs text-muted">{t('Исход по умолчанию')}</span>
                    ) : (
                      <Chip tone="ev" className="self-start">
                        {t('Изменено: по умолчанию «{d}»', { d: t(OUTCOMES.find(x => x[0] === r.default)?.[1] ?? r.default) })}
                      </Chip>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </>
  );
}
