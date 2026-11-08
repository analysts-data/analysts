// Экран «Правила обработки»: какой оценщик и с какими настройками берёт диалог. Правила по порядку, первое
// подходящее выигрывает, правило по умолчанию («Режим оценки») всегда последнее. GET/PUT /api/routing,
// POST /api/routing/explain; провайдеры для выбора — GET /api/config. Каждое изменение сохраняется сразу.
import { ArrowDown, ArrowUp, Check, Plus, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { titleOf } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { api, toast, userHeader } from '../lib/state.js';
import { useS } from '../store';
import { Button, Card, Chip, cn, Field, Modal, PageHead, Skeleton, Tip } from '../ui';

const DEFAULT = 'default';
const INHERIT = '__mode'; // «как в Режиме оценки»: поле use не задано

type Errs = { fields: Record<string, string>; general: string[] };
const NO_ERRS: Errs = { fields: {}, general: [] };

const list = (s: string) => {
  const v = s
    .split(',')
    .map(x => x.trim())
    .filter(Boolean);
  return v.length ? v : undefined;
};
const int = (s: string) => (s.trim() === '' ? undefined : Number(s));

/** Условия правила словами: «звонок и язык KZ». */
function conds(m: any = {}): string[] {
  const out: string[] = [];
  if (m.ch) out.push(m.ch === 'call' ? t('звонок') : t('чат'));
  if (m.lang?.length) out.push(t('язык {v}', { v: m.lang.join(', ') }));
  if (m.source_id?.length) out.push(t('источник {v}', { v: m.source_id.join(', ') }));
  if (m.product?.length) out.push(t('продукт {v}', { v: m.product.join(', ') }));
  if (m.min_lines != null) out.push(t('не меньше {n} реплик', { n: m.min_lines }));
  if (m.max_lines != null) out.push(t('не больше {n} реплик', { n: m.max_lines }));
  if (m.has_audio != null) out.push(m.has_audio ? t('есть запись') : t('нет записи'));
  return out;
}

/** Действия правила словами: «основная модель, второе мнение Jev, интонация». */
function uses(u: any = {}, label: (id: string) => string): string[] {
  const out: string[] = [];
  if (u.evaluator === 'jev') out.push(t('только Jev'));
  else out.push(u.llm_provider ? t('модель {name}', { name: label(u.llm_provider) }) : t('основная модель'));
  if ('verifier' in u) out.push(u.verifier == null ? t('без второго мнения') : t('второе мнение {name}', { name: u.verifier === 'jev' ? 'Jev' : label(u.verifier) }));
  if (u.anonymize) out.push(t('обезличивание'));
  if (u.prosody === true) out.push(t('интонация'));
  if (u.prosody === false) out.push(t('без интонации'));
  if (u.max_parallel) out.push(t('до {n} запросов одновременно', { n: u.max_parallel }));
  return out;
}

function sentence(r: any, label: (id: string) => string) {
  if (r.id === DEFAULT) return t('Все остальные диалоги → общий «Режим оценки»');
  const c = conds(r.match);
  const head = c.length ? t('Если {cond}', { cond: c.join(' ' + t('и') + ' ') }) : t('Любой диалог');
  return `${head} → ${uses(r.use, label).join(', ')}`;
}

/**
 * Ошибки 422 по полям правила `i`. Сервер присылает `fields` ({путь: текст} или [{loc|field, msg}]) или строки
 * «правило 2 «…» → use.llm_provider: текст»; путь — «1.use.llm_provider», «body.1.match.lang» или «use.llm_provider».
 */
function errorsOf(body: any, text: string, i: number): Errs {
  const out: Errs = { fields: {}, general: [] };
  const add = (path: string, msg: string) => {
    const segs = path.split('.').filter(s => s !== 'body' && s !== 'rules');
    const n = segs.findIndex(s => /^\d+$/.test(s));
    if (n >= 0 && Number(segs[n]) !== i) return out.general.push(t('Правило {n}: {msg}', { n: Number(segs[n]) + 1, msg }));
    const key = segs.slice(n + 1).join('.');
    if (key && FIELDS.includes(key)) out.fields[key] = msg;
    else out.general.push(key ? `${key}: ${msg}` : msg);
  };
  const items = (f: any) =>
    Array.isArray(f)
      ? f.forEach((x: any) => add(String(x.field ?? x.path ?? (x.loc ?? []).join('.')), String(x.msg ?? x.message ?? '')))
      : Object.entries(f).forEach(([k, v]) => add(k, String(v)));
  const fields = body?.fields ?? body?.detail?.fields;
  const detail = body?.detail;
  if (fields) items(fields);
  else if (Array.isArray(detail)) items(detail);
  else
    String(typeof detail === 'string' ? detail : text)
      .split('\n')
      .filter(Boolean)
      .forEach(line => {
        const m = line.match(/^правило (\d+)[^→]*→\s*([\w.]+):\s*(.+)$/);
        if (m) add(`${Number(m[1]) - 1}.${m[2]}`, m[3]);
        else out.general.push(line);
      });
  return out;
}

const FIELDS = [
  'name',
  'why',
  'match.ch',
  'match.lang',
  'match.source_id',
  'match.product',
  'match.min_lines',
  'match.max_lines',
  'match.has_audio',
  'use.evaluator',
  'use.llm_provider',
  'use.verifier',
  'use.anonymize',
  'use.prosody',
  'use.max_parallel',
];

/** PUT /api/routing напрямую: клиенту api тело ошибки 422 с полями не видно. */
async function putRules(next: any[]): Promise<{ ok: boolean; status: number; body: any; text: string }> {
  const res = await fetch(api.base + '/routing', {
    method: 'PUT',
    headers: { ...userHeader(), 'Content-Type': 'application/json' },
    body: JSON.stringify(next),
  });
  const text = await res.text();
  let body: any = null;
  try {
    body = JSON.parse(text);
  } catch {
    /* тело не JSON */
  }
  return { ok: res.ok, status: res.status, body, text };
}

const toForm = (r: any) => {
  const m = r.match ?? {},
    u = r.use ?? {};
  const s = (v: any) => (v == null ? '' : String(v));
  return {
    name: r.name ?? '',
    why: r.why ?? '',
    enabled: r.enabled !== false,
    ch: m.ch ?? '',
    lang: (m.lang ?? []).join(', '),
    source_id: (m.source_id ?? []).join(', '),
    product: (m.product ?? []).join(', '),
    min_lines: s(m.min_lines),
    max_lines: s(m.max_lines),
    has_audio: m.has_audio == null ? '' : m.has_audio ? 'yes' : 'no',
    evaluator: u.evaluator ?? '',
    llm_provider: u.llm_provider ?? '',
    verifier: 'verifier' in u ? (u.verifier ?? '') : INHERIT,
    anonymize: !!u.anonymize,
    prosody: u.prosody == null ? '' : u.prosody ? 'on' : 'off',
    max_parallel: s(u.max_parallel),
  };
};
type Form = ReturnType<typeof toForm>;

function fromForm(id: string, f: Form) {
  const drop = (o: Record<string, any>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== ''));
  const use: Record<string, any> = drop({
    evaluator: f.evaluator,
    llm_provider: f.llm_provider,
    anonymize: f.anonymize || undefined,
    prosody: f.prosody ? f.prosody === 'on' : undefined,
    max_parallel: int(f.max_parallel),
  });
  if (f.verifier !== INHERIT) use.verifier = f.verifier || null;
  return {
    id,
    name: f.name.trim(),
    enabled: f.enabled,
    why: f.why.trim() || null,
    match: drop({
      ch: f.ch,
      lang: list(f.lang),
      source_id: list(f.source_id),
      product: list(f.product),
      min_lines: int(f.min_lines),
      max_lines: int(f.max_lines),
      has_audio: f.has_audio ? f.has_audio === 'yes' : undefined,
    }),
    use,
  };
}

/** Проверка до отправки: то, что сервер всё равно отклонит. */
function check(f: Form): Record<string, string> {
  const out: Record<string, string> = {};
  const nonneg = (s: string) => s.trim() === '' || (Number.isInteger(Number(s)) && Number(s) >= 0);
  if (!f.name.trim()) out.name = t('Назовите правило: имя видно в списке и в карточке диалога.');
  if (!nonneg(f.min_lines)) out['match.min_lines'] = t('Целое число от 0.');
  if (!nonneg(f.max_lines)) out['match.max_lines'] = t('Целое число от 0.');
  if (!out['match.min_lines'] && !out['match.max_lines'] && f.min_lines.trim() && f.max_lines.trim() && Number(f.min_lines) > Number(f.max_lines))
    out['match.max_lines'] = t('Не меньше минимума, иначе правило не подойдёт ни одному диалогу.');
  if (f.max_parallel.trim() && !(Number.isInteger(Number(f.max_parallel)) && Number(f.max_parallel) >= 1)) out['use.max_parallel'] = t('Целое число от 1.');
  return out;
}

function Editor({ rules, index, providers, onClose, onSaved }: { rules: any[]; index: number; providers: any[]; onClose: () => void; onSaved: (r: any[]) => void }) {
  const isNew = index < 0;
  const at = isNew ? rules.length - 1 : index; // новое правило — перед правилом по умолчанию
  const [f, setF] = useState<Form>(() => toForm(isNew ? { enabled: true } : rules[index]));
  const [errs, setErrs] = useState<Errs>(NO_ERRS);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Form, v: any) => setF({ ...f, [k]: v });
  const err = (k: string) => errs.fields[k] && <span className="text-xs text-risk">{errs.fields[k]}</span>;
  const [id] = useState(() => (isNew ? `rule-${Date.now().toString(36)}` : rules[index].id));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const local = check(f);
    if (Object.keys(local).length) return setErrs({ fields: local, general: [] });
    const rule = fromForm(id, f);
    const next = isNew ? [...rules.slice(0, at), rule, ...rules.slice(at)] : rules.map((r, i) => (i === index ? rule : r));
    setBusy(true);
    try {
      const res = await putRules(next);
      if (res.ok) {
        toast(t('Правило сохранено.'));
        return onSaved(res.body);
      }
      setErrs(res.status === 422 ? errorsOf(res.body, res.text, at) : { fields: {}, general: [res.body?.detail ?? res.text] });
    } catch (e: any) {
      setErrs({ fields: {}, general: [e.message] });
    }
    setBusy(false);
  }

  async function remove() {
    if (!confirm(t('Удалить правило «{name}»?', { name: rules[index].name }))) return;
    const res = await putRules(rules.filter((_, i) => i !== index));
    if (res.ok) {
      toast(t('Правило удалено.'));
      onSaved(res.body);
    } else setErrs({ fields: {}, general: [res.body?.detail ?? res.text] });
  }

  const sel = (label: string, k: keyof Form, vals: [string, string][], hint?: string) => (
    <Field label={label} hint={hint}>
      <select className="fld" value={f[k] as string} aria-invalid={!!errs.fields[`${k === 'ch' || k === 'has_audio' ? 'match' : 'use'}.${k}`]} onChange={e => set(k, e.target.value)}>
        {vals.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
      {err(`${k === 'ch' || k === 'has_audio' ? 'match' : 'use'}.${k}`)}
    </Field>
  );
  const txt = (label: string, k: keyof Form, path: string, hint?: string, type = 'text') => (
    <Field label={label} hint={hint}>
      <input type={type} min={type === 'number' ? 0 : undefined} className="fld" value={f[k] as string} aria-invalid={!!errs.fields[path]} onChange={e => set(k, e.target.value)} />
      {err(path)}
    </Field>
  );
  const mode = t('Как в «Режиме оценки»');
  const prov: [string, string][] = providers.map(p => [p.id, p.label ?? p.id]);

  return (
    <Modal open wide onOpenChange={v => !v && onClose()} title={isNew ? t('Новое правило') : t('Изменить правило')} description={t('Условия выбирают диалоги, действия меняют общий «Режим оценки» только для них. Пустое поле: условия нет или настройка как в общем режиме.')}>
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          {txt(t('Название'), 'name', 'name')}
          <label className="flex items-center gap-2 self-end pb-2.5 text-sm">
            <input type="checkbox" checked={f.enabled} onChange={e => set('enabled', e.target.checked)} />
            {t('Правило включено')}
          </label>
        </div>
        <Field label={t('Зачем это правило')} hint={t('Видно в списке правил: почему такие диалоги оцениваются иначе.')}>
          <textarea className="fld min-h-16" value={f.why} onChange={e => set('why', e.target.value)} />
        </Field>
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-1.5 text-[15px] font-semibold">{t('Если')}</legend>
          {sel(t('Канал'), 'ch', [
            ['', t('Любой')],
            ['chat', t('Чат')],
            ['call', t('Звонок')],
          ])}
          {txt(t('Язык'), 'lang', 'match.lang', t('Через запятую: KZ, RU'))}
          {sel(t('Запись разговора'), 'has_audio', [
            ['', t('Неважно')],
            ['yes', t('Есть')],
            ['no', t('Нет')],
          ])}
          {txt(t('Продукт'), 'product', 'match.product', t('Через запятую'))}
          {txt(t('Источник'), 'source_id', 'match.source_id', t('Через запятую'))}
          <div className="grid grid-cols-2 gap-3">
            {txt(t('Реплик от'), 'min_lines', 'match.min_lines', undefined, 'number')}
            {txt(t('Реплик до'), 'max_lines', 'match.max_lines', undefined, 'number')}
          </div>
        </fieldset>
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-1.5 text-[15px] font-semibold">{t('То')}</legend>
          {sel(t('Оценщик'), 'evaluator', [
            ['', mode],
            ['llm', t('Модель с обоснованиями')],
            ['jev', t('Только Jev')],
          ])}
          {sel(t('Основная модель'), 'llm_provider', [['', mode], ...prov])}
          {sel(t('Второе мнение'), 'verifier', [[INHERIT, mode], ['', t('Без второго мнения')], ['jev', 'Jev'], ...prov])}
          {sel(t('Интонация по записи'), 'prosody', [
            ['', mode],
            ['on', t('Учитывать')],
            ['off', t('Не учитывать')],
          ])}
          {txt(t('Запросов одновременно'), 'max_parallel', 'use.max_parallel', undefined, 'number')}
          <label className="flex items-center gap-2 self-end pb-2.5 text-sm">
            <input type="checkbox" checked={f.anonymize} onChange={e => set('anonymize', e.target.checked)} />
            {t('Обезличивать')}
          </label>
        </fieldset>
        {err('use.anonymize')}
        <p className="text-[13px] text-ink2" data-act="rule-preview">
          {sentence(fromForm(id, f), pid => providers.find(p => p.id === pid)?.label ?? pid)}
        </p>
        {errs.general.length > 0 && (
          <div className="box risk" role="alert">
            {errs.general.map((g, i) => (
              <p key={i}>{g}</p>
            ))}
          </div>
        )}
        <div className="flex flex-wrap justify-between gap-2.5">
          <div>
            {!isNew && (
              <Button variant="danger" onClick={remove}>
                {t('Удалить правило')}
              </Button>
            )}
          </div>
          <div className="flex gap-2.5">
            <Button onClick={onClose}>{t('Отмена')}</Button>
            <Button type="submit" variant="primary" data-act="rule-save" disabled={busy}>
              {busy ? t('Сохраняем…') : t('Сохранить правило')}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

/** «Проверить на диалоге»: какое правило возьмёт диалог и какие условия каждого правила выполнены. */
function Explain() {
  const S = useS();
  const dialogs: any[] = S.dialogs ?? [];
  const [did, setDid] = useState('');
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const pick = did || dialogs[0]?.id || '';
  async function run() {
    setBusy(true);
    try {
      setRes(await api.post('/routing/explain', { dialog_id: pick }));
    } catch (e: any) {
      toast(t('Проверка не выполнена: {e}', { e: e.message }));
    } finally {
      setBusy(false);
    }
  }
  const shown = res ? res.rules.slice(0, res.rules.findIndex((r: any) => r.chosen) + 1 || undefined) : [];
  return (
    <Card aria-label={t('Проверить на диалоге')}>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-[15px] font-semibold">{t('Проверить на диалоге')}</h2>
          <p className="text-xs text-muted">{t('Какое правило возьмёт диалог по сохранённым правилам и почему не подошли правила выше.')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="fld max-w-[280px]" aria-label={t('Диалог')} value={pick} onChange={e => setDid(e.target.value)}>
            {dialogs.map(d => (
              <option key={d.id} value={d.id}>
                {titleOf(d)}
              </option>
            ))}
          </select>
          <Button data-act="routing-explain" disabled={busy || !pick} onClick={run}>
            {busy ? t('Проверяем…') : t('Проверить')}
          </Button>
        </div>
      </div>
      {!dialogs.length && <p className="px-4 py-3 text-muted">{t('Диалогов нет: загрузите набор на экране «Диалоги».')}</p>}
      {res && (
        <div className="flex flex-col gap-3 px-4 py-3.5" data-act="explain-result">
          <p>
            {t('Диалог возьмёт правило')} <b>«{res.rule?.name}»</b>
          </p>
          <ol className="flex flex-col divide-y divide-line2">
            {shown.map((r: any) => (
              <li key={r.id} className="py-2" data-rule={r.id} data-matched={r.matched ? 'yes' : 'no'}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className={cn('font-semibold', !r.chosen && 'text-ink2')}>{r.name}</span>
                  {r.chosen ? <Chip tone="ok">{t('Выбрано')}</Chip> : !r.enabled ? <Chip tone="na">{t('Выключено')}</Chip> : <Chip tone="na">{t('Не подошло')}</Chip>}
                </div>
                {r.conditions?.length ? (
                  <ul className="mt-1 flex flex-col gap-0.5 text-[13px]">
                    {r.conditions.map((c: any, i: number) => (
                      <li key={i} className="flex items-start gap-1.5" data-ok={c.ok ? 'yes' : 'no'}>
                        {c.ok ? <Check size={16} className="mt-0.5 shrink-0 text-accent" aria-label={t('выполнено')} /> : <X size={16} className="mt-0.5 shrink-0 text-risk" aria-label={t('не выполнено')} />}
                        <span>{c.text}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-[13px] text-muted">{t('Без условий: подходит любому диалогу.')}</p>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
}

export function Routing(_: { id: string | null }) {
  const S = useS();
  const [rules, setRules] = useState<any[] | null>(null);
  const [error, setError] = useState('');
  const [providers, setProviders] = useState<any[]>([]);
  const [editing, setEditing] = useState<number | null>(null); // -1 — новое правило
  const [busy, setBusy] = useState(false);
  const canEdit = S.role === 'qa';
  const label = (pid: string) => providers.find(p => p.id === pid)?.label ?? pid;

  async function load() {
    try {
      setRules(await api.get('/routing'));
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }
  useEffect(() => {
    load();
    api.getConfig().then(
      (c: any) => setProviders(c?.providers ?? []),
      () => {},
    );
  }, []);

  async function save(next: any[], done: string) {
    setBusy(true);
    try {
      const res = await putRules(next);
      if (res.ok) {
        setRules(res.body);
        toast(done);
      } else toast(t('Не сохранено: {e}', { e: res.body?.detail ?? res.text }));
    } catch (e: any) {
      toast(t('Не сохранено: {e}', { e: e.message }));
    } finally {
      setBusy(false);
    }
  }
  const move = (i: number, d: number) => {
    const next = rules!.slice();
    [next[i], next[i + d]] = [next[i + d], next[i]];
    save(next, t('Порядок правил сохранён.'));
  };

  return (
    <>
      <PageHead title={t('Правила обработки')} sub={t('Разные модели и настройки для звонков, чатов, языков и продуктов. Правила проверяются сверху вниз, диалог берёт первое подходящее.')}>
        {canEdit && rules && (
          <Button variant="primary" data-act="rule-new" onClick={() => setEditing(-1)}>
            <Plus size={16} aria-hidden="true" /> {t('Новое правило')}
          </Button>
        )}
      </PageHead>
      <Card aria-label={t('Список правил')}>
        {error ? (
          <div className="flex flex-col items-start gap-3 p-5">
            <p className="text-risk">{t('Правила не загрузились: {e}', { e: error })}</p>
            <Button onClick={load}>{t('Повторить')}</Button>
          </div>
        ) : rules == null ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : (
          <ol className="divide-y divide-line2">
            {rules.map((r, i) => {
              const isDefault = r.id === DEFAULT;
              const last = i === rules.length - 2; // ниже — только правило по умолчанию
              return (
                <li key={r.id} data-rule={r.id} className={cn('flex flex-wrap items-start gap-3 px-4 py-3', r.enabled === false && 'text-muted')}>
                  <span className="num w-6 shrink-0 pt-0.5 text-right text-[13px] text-muted">{i + 1}</span>
                  <div className="min-w-0 flex-[1_1_320px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn('font-semibold', r.enabled !== false && 'text-ink')}>{r.name}</span>
                      {r.enabled === false && <Chip tone="na">{t('Выключено')}</Chip>}
                    </div>
                    <p className={cn('text-[13px]', r.enabled === false ? 'text-muted' : 'text-ink2')} data-act="rule-sentence">
                      {sentence(r, label)}
                    </p>
                    {r.why && <p className="mt-0.5 text-xs text-muted">{r.why}</p>}
                  </div>
                  {isDefault ? (
                    <span className="max-w-[260px] text-xs text-muted">{t('Всегда последнее. Модель и настройки меняются в «Режиме оценки».')}</span>
                  ) : (
                    canEdit && (
                      <div className="flex items-center gap-1.5">
                        <label className="mr-2 flex items-center gap-1.5 text-[13px] text-ink2">
                          <input type="checkbox" data-act="rule-toggle" checked={r.enabled !== false} disabled={busy} onChange={e => save(rules.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x)), e.target.checked ? t('Правило включено.') : t('Правило выключено.'))} />
                          {t('Включено')}
                        </label>
                        <Tip content={t('Выше')}>
                          <Button size="sm" variant="ghost" aria-label={t('Выше')} data-act="rule-up" disabled={busy || i === 0} onClick={() => move(i, -1)}>
                            <ArrowUp size={16} aria-hidden="true" />
                          </Button>
                        </Tip>
                        <Tip content={t('Ниже')}>
                          <Button size="sm" variant="ghost" aria-label={t('Ниже')} data-act="rule-down" disabled={busy || last} onClick={() => move(i, 1)}>
                            <ArrowDown size={16} aria-hidden="true" />
                          </Button>
                        </Tip>
                        <Button size="sm" data-act="rule-edit" onClick={() => setEditing(i)}>
                          {t('Изменить')}
                        </Button>
                      </div>
                    )
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </Card>
      {!canEdit && <p className="text-[13px] text-muted">{t('Правила меняет специалист КК.')}</p>}
      <Explain />
      {editing != null && rules && (
        <Editor
          rules={rules}
          index={editing}
          providers={providers}
          onClose={() => setEditing(null)}
          onSaved={r => {
            setRules(r);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
