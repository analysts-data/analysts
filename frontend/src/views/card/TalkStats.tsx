// «Статистика разговора» (GET /api/dialogs/{id}/talkstats): метрики времени разговора рядом с медианой команды.
// Только время: длительности речи, паузы, перебивания, темп. Загружается по кнопке: звонку нужен разбор записи на сервере.
import { useState } from 'react';
import { t } from '../../lib/i18n.js';
import { api } from '../../lib/state.js';
import { Button, Card, Chip } from '../../ui';

const num = (x: number | null | undefined) => (x == null ? '—' : x.toLocaleString(undefined, { maximumFractionDigits: 1 }));

export function TalkStats({ id }: { id: string }) {
  const [st, setSt] = useState<{ busy?: boolean; data?: any; err?: string; none?: boolean }>({});
  const load = async () => {
    setSt({ busy: true });
    try {
      setSt({ data: await api.get(`/dialogs/${encodeURIComponent(id)}/talkstats`) });
    } catch (e: any) {
      if (e?.status === 404) setSt({ none: true });
      else setSt({ err: e?.status === 502 ? t('Запись звонка не получена, статистику посчитать нельзя.') : String(e?.message ?? e) });
    }
  };
  const d = st.data;
  return (
    <Card className="flex flex-col gap-3 px-4 py-3.5" data-talkstats>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-semibold">{t('Статистика разговора')}</h2>
          <p className="text-xs text-muted">{t('Доля речи, паузы, перебивания и темп рядом с медианой команды. Содержание реплик не учитывается.')}</p>
        </div>
        {!d && (
          <Button size="sm" onClick={load} disabled={st.busy}>
            {st.busy ? t('Считается…') : t('Показать статистику')}
          </Button>
        )}
      </div>
      {st.none && <p className="text-[13px] text-muted">{t('Для этого диалога статистики нет: нет записи или меток времени у ответов оператора.')}</p>}
      {st.err && <p className="box ev">{st.err}</p>}
      {d && (
        <>
          <ul className="divide-y divide-line2">
            {d.metrics.map((m: any) => (
              <li key={m.key} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-x-4 py-2 text-[13px]">
                <span className="min-w-0 text-ink2">{m.label}</span>
                <span className="tabular text-right font-semibold">
                  {num(m.value)} {m.value != null && m.unit}
                  {m.out_of_norm === true && (
                    <Chip tone="ev" className="ml-2">
                      {t('вне нормы')}
                    </Chip>
                  )}
                </span>
                <span className="tabular w-32 text-right text-xs text-muted">{m.median == null ? '' : t('медиана {v}', { v: `${num(m.median)} ${m.unit}` })}</span>
              </li>
            ))}
          </ul>
          {d.note && <p className="text-xs text-muted">{d.note}</p>}
          <p className="text-xs text-muted">{d.rule}</p>
        </>
      )}
    </Card>
  );
}

/** Нормы команды (GET /api/talkstats/norms): медианы сотрудника рядом с медианами команды, по звонкам и чатам. */
export function TalkNorms({ operator }: { operator: string }) {
  const [st, setSt] = useState<{ busy?: boolean; data?: any; err?: string }>({});
  const load = async () => {
    setSt({ busy: true });
    try {
      setSt({ data: await api.get('/talkstats/norms') });
    } catch (e: any) {
      setSt({ err: String(e?.message ?? e) });
    }
  };
  const d = st.data;
  const mine = d?.operators?.[operator];
  return (
    <Card className="flex flex-col gap-3 px-4 py-3.5" data-talknorms>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-semibold">{t('Статистика разговора')}</h2>
          <p className="text-xs text-muted">{t('Медианы сотрудника рядом с медианами команды по звонкам и чатам.')}</p>
        </div>
        {!d && (
          <Button size="sm" onClick={load} disabled={st.busy}>
            {st.busy ? t('Загружаю…') : t('Показать статистику')}
          </Button>
        )}
      </div>
      {st.err && <p className="box ev">{st.err}</p>}
      {d &&
        (['call', 'chat'] as const).map(ch => {
          const team = d[ch];
          if (!team?.metrics?.length) return null;
          if (!team.n)
            return (
              <p key={ch} className="text-[13px] text-muted">
                {ch === 'call' ? t('Звонки: у команды пока нет разобранных записей.') : t('Чаты: у команды пока нет ответов с метками времени.')}
              </p>
            );
          const own = Object.fromEntries((mine?.[ch]?.metrics ?? []).map((m: any) => [m.key, m]));
          return (
            <div key={ch} className="flex flex-col gap-1">
              <h3 className="text-[13px] font-semibold text-ink2">{ch === 'call' ? t('Звонки') : t('Чаты')}</h3>
              <ul className="divide-y divide-line2">
                {team.metrics.map((m: any) => (
                  <li key={m.key} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-4 py-1.5 text-[13px]">
                    <span className="text-ink2">{m.label}</span>
                    <span className="tabular text-right font-semibold">{own[m.key]?.median == null ? '—' : `${num(own[m.key].median)} ${m.unit}`}</span>
                    <span className="tabular w-32 text-right text-xs text-muted">{m.median == null ? '' : t('команда {v}', { v: `${num(m.median)} ${m.unit}` })}</span>
                  </li>
                ))}
              </ul>
              {(mine?.[ch]?.note ?? team.note) && <p className="text-xs text-muted">{mine?.[ch]?.note ?? team.note}</p>}
            </div>
          );
        })}
      {d && <p className="text-xs text-muted">{d.rule}</p>}
    </Card>
  );
}
