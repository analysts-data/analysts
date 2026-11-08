// «Правила алертов»: GET /api/alerts/rules, включение, важность, пороги и обоснование, PUT всего списка.
// Ошибки сервера — 422 {detail: [{loc: ["body", i, поле, параметр], msg}]}, показываются у своего правила.
import { useEffect, useState } from 'react';
import { msg, t } from '../../lib/i18n.js';
import { api, toast } from '../../lib/state.js';
import { Button, cn, Modal, Skeleton } from '../../ui';

// Что проверяет вид правила (src/cqa/domain/alerts.py, PARAMS).
const KIND: Record<string, string> = {
  gross_error: msg('В диалоге грубое нарушение'),
  low_total: msg('Итог диалога ниже порога'),
  operator_avg: msg('Средний итог оператора по последним диалогам ниже порога'),
  no_next_step_share: msg('Доля диалогов без следующего шага выше порога'),
  raised_tone: msg('Клиент повысил тон в звонке'),
  appeal_overdue: msg('Апелляция без решения дольше срока'),
  run_errors: msg('Прогон оценки закончился с ошибками'),
  marker: msg('На диалоге стоит ручной маркер'),
  long_silence: msg('Тишина в звонке дольше порога'),
  risk: msg('В диалоге найден риск'),
};
// Параметры вида: ключ, подпись; label и k — строки, остальные — числа.
const PARAMS: Record<string, [string, string][]> = {
  low_total: [['threshold', msg('Итог ниже')]],
  operator_avg: [
    ['n', msg('Последних диалогов')],
    ['threshold', msg('Средний итог ниже')],
    ['min_dialogs', msg('Минимум диалогов')],
  ],
  no_next_step_share: [
    ['threshold', msg('Доля выше, %')],
    ['min_dialogs', msg('Минимум диалогов')],
  ],
  appeal_overdue: [['hours', msg('Дольше, ч')]],
  long_silence: [['seconds', msg('Тишина дольше, с')]],
  marker: [['label', msg('Маркер')]],
  risk: [['k', msg('Ключ риска')]],
};
const TEXT = new Set(['label', 'k']);
const SEVERITY: [string, string][] = [
  ['critical', msg('Критичный')],
  ['warning', msg('Предупреждение')],
  ['info', msg('Сведения')],
];

export function RulesDialog({ onClose }: { onClose: () => void }) {
  const [rules, setRules] = useState<any[] | null>(null);
  const [loadErr, setLoadErr] = useState('');
  const [errs, setErrs] = useState<Record<number, string[]>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get('/alerts/rules').then(setRules, (e: any) => setLoadErr(e.message));
  }, []);
  const edit = (i: number, patch: any) => setRules(rs => rs!.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const param = (i: number, k: string, v: string) => {
    const p = { ...rules![i].params };
    if (v === '')
      delete p[k]; // пусто — значение по умолчанию сервера
    else p[k] = TEXT.has(k) ? v : Number(v);
    edit(i, { params: p });
  };

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.put('/alerts/rules', rules);
      toast(t('Правила алертов сохранены. Они сработают при следующей проверке.'));
      onClose();
    } catch (x: any) {
      const by: Record<number, string[]> = {};
      for (const d of Array.isArray(x.body?.detail) ? x.body.detail : []) (by[d.loc?.[1]] ??= []).push(d.msg);
      setErrs(by);
      setBusy(false);
      toast(Object.keys(by).length ? t('Правила не сохранены: исправьте отмеченные правила.') : t('Правила не сохранены: {e}', { e: x.message }));
    }
  }

  return (
    <Modal
      open
      wide
      onOpenChange={v => !v && onClose()}
      title={t('Правила алертов')}
      description={t('Когда создаётся алерт и насколько он важен. Проверка идёт после оценки, апелляции, решения и правки маркеров.')}
    >
      {loadErr ? (
        <p className="text-risk">{t('Правила не загрузились: {e}', { e: loadErr })}</p>
      ) : rules == null ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : (
        <form onSubmit={save} noValidate>
          <ul className="divide-y divide-line2">
            {rules.map((r, i) => (
              <li key={r.id} className="flex flex-col gap-2 py-3 first:pt-0" data-rule={r.id}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--accent)]"
                    data-act="rule-on"
                    aria-label={t('Правило включено')}
                    checked={r.enabled !== false}
                    onChange={e => edit(i, { enabled: e.target.checked })}
                  />
                  <input
                    className={cn('fld min-w-0 flex-1 font-semibold', r.enabled === false && 'text-muted')}
                    aria-label={t('Название правила')}
                    value={r.title}
                    onChange={e => edit(i, { title: e.target.value })}
                  />
                  <select className="fld w-auto" aria-label={t('Важность')} data-act="rule-severity" value={r.severity} onChange={e => edit(i, { severity: e.target.value })}>
                    {SEVERITY.map(([v, l]) => (
                      <option key={v} value={v}>
                        {t(l)}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="text-xs text-muted">
                  {KIND[r.kind] ? t(KIND[r.kind]) : r.kind}
                  {r.enabled === false && t('. Выключено: алертов по нему не будет.')}
                </p>
                {(PARAMS[r.kind] ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-3">
                    {PARAMS[r.kind].map(([k, l]) => (
                      <label key={k} className="flex flex-col gap-1">
                        <span className="text-xs text-muted">{t(l)}</span>
                        <input className="fld w-32" type={TEXT.has(k) ? 'text' : 'number'} data-param={k} value={r.params?.[k] ?? ''} onChange={e => param(i, k, e.target.value)} />
                      </label>
                    ))}
                  </div>
                )}
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted">{t('Почему такое правило и порог')}</span>
                  <textarea className="fld !min-h-14 text-[13px]" rows={2} value={r.why ?? ''} onChange={e => edit(i, { why: e.target.value })} />
                </label>
                {errs[i]?.map(m => (
                  <p key={m} className="text-[13px] text-risk">
                    {m}
                  </p>
                ))}
              </li>
            ))}
          </ul>
          <div className="sticky bottom-0 -mx-5 -mb-4 mt-2 flex justify-end gap-2.5 border-t border-line bg-surface px-5 py-3">
            <Button onClick={onClose}>{t('Отмена')}</Button>
            <Button type="submit" variant="primary" data-act="rules-save" disabled={busy}>
              {busy ? t('Сохраняем…') : t('Сохранить правила')}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
