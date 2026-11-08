// «Источники данных»: реестр источников диалогов, здоровье с «Почему» (basis сервера), синхронизация, журнал
// и мастер добавления: вид → подключение → сопоставление полей с предпросмотром /test → проверка → сохранение.
import { Copy } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { t } from '../lib/i18n.js';
import { reload, toast } from '../lib/state.js';
import { Button, Card, Chip, cn, Empty, Field, Modal, PageHead, Skeleton, Tip, type Tone } from '../ui';
import { apiUrl, pct } from './people/net';
import { ago, type Fields, send, when } from './sources/net';

const enc = encodeURIComponent;
const PULL = ['org_api', 'http_json']; // сервер забирает сам: по расписанию или кнопкой
const BUILTIN = ['file', 'paste', 'api'];
const NEW_KINDS = ['http_json', 'webhook', 'org_api'];

const kinds = (): Record<string, [string, string]> => ({
  http_json: [t('HTTP JSON'), t('CQA сам забирает диалоги по адресу: по расписанию или кнопкой.')],
  webhook: [t('Webhook'), t('Внешний сервис сам присылает диалоги на адрес CQA.')],
  org_api: [t('API организаторов'), t('Набор по group_id с сервера организаторов.')],
  file: [t('Файл'), ''],
  paste: [t('Вставка текста'), ''],
  api: [t('Интеграционный API'), ''],
});
const HEALTH: Record<string, [() => string, Tone]> = {
  ok: [() => t('Работает'), 'ok'],
  warning: [() => t('Внимание'), 'ev'],
  error: [() => t('Ошибка'), 'risk'],
};
const SYNC: Record<string, [() => string, Tone]> = {
  ok: [() => t('успешно'), 'ok'],
  partial: [() => t('с пропусками'), 'ev'],
  error: [() => t('с ошибкой'), 'risk'],
  running: [() => t('идёт'), 'info'],
};
// [поле, подпись, обязательное]; пути внутри реплики: speaker, text, timestamp
const mapFields = (): [string, string, boolean][] => [
  ['conversation_id', t('ID диалога'), true],
  ['transcript', t('Список реплик'), true],
  ['speaker', t('Кто говорит (в реплике)'), true],
  ['text', t('Текст реплики'), true],
  ['timestamp', t('Время реплики'), false],
  ['channel', t('Канал'), false],
  ['language', t('Язык'), false],
  ['operator', t('Оператор'), false],
  ['product', t('Продукт'), false],
  ['audio_url', t('Ссылка на запись'), false],
];
const DEFAULT_MAP = { conversation_id: 'id', transcript: 'messages', speaker: 'role', text: 'text' };
const configFor = (kind: string): any =>
  kind === 'org_api'
    ? { group_id: '' }
    : kind === 'webhook'
      ? { auth: 'bearer', records_path: '', mapping: { ...DEFAULT_MAP } }
      : { url: '', method: 'GET', records_path: '', auth_header: '', mapping: { ...DEFAULT_MAP } };

const ingestUrl = (s: any) => new URL(apiUrl(s.ingest_path ?? `/api/sources/${enc(s.id)}/ingest`), location.href).href;

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t('Скопировано.'));
  } catch {
    toast(t('Не скопировано: выделите текст и скопируйте вручную.'));
  }
}

function CopyField({ label, value, act }: { label: string; value: string; act: string }) {
  return (
    <Field label={label}>
      <span className="flex gap-2">
        <input className="fld min-w-0 flex-1 font-mono text-[13px]" readOnly value={value} onFocus={e => e.target.select()} />
        <Tip content={t('Скопировать')}>
          <Button aria-label={t('Скопировать')} data-act={act} onClick={() => copy(value)}>
            <Copy size={16} aria-hidden="true" />
          </Button>
        </Tip>
      </span>
    </Field>
  );
}

type Step = 'type' | 'connect' | 'fields' | 'check' | 'token';

function Wizard({ src, onClose, onSaved }: { src: any; onClose: () => void; onSaved: () => void }) {
  const editing = !!src.id;
  const [f, setF] = useState<any>(() =>
    editing
      ? { ...src, service: src.service ?? '', channel_default: src.channel_default ?? '', product_default: src.product_default ?? '', config: { ...configFor(src.kind), ...src.config }, secret: '', sample: '' }
      : { name: '', kind: '', service: '', channel_default: '', product_default: '', enabled: true, schedule_min: 60, config: {}, secret: '', sample: '' },
  );
  const [step, setStep] = useState<Step>(editing ? 'connect' : 'type');
  const [errs, setErrs] = useState<Fields>({});
  const [test, setTest] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<{ token: string; url: string } | null>(null);
  const seq = useRef(0);

  const steps: [Step, string][] = [
    ['type', t('Вид')],
    ['connect', t('Подключение')],
    ...(f.kind === 'org_api' ? [] : ([['fields', t('Поля')]] as [Step, string][])),
    ['check', t('Проверка')],
  ];
  const at = steps.findIndex(([s]) => s === step);
  const set = (k: string, v: unknown) => setF((x: any) => ({ ...x, [k]: v }));
  const setCfg = (k: string, v: unknown) => setF((x: any) => ({ ...x, config: { ...x.config, [k]: v } }));
  const setMap = (k: string, v: string) => setF((x: any) => ({ ...x, config: { ...x.config, mapping: { ...x.config.mapping, [k]: v } } }));
  const err = (k: string, hint?: string) => (errs[k] ? <span className="text-risk">{errs[k]}</span> : hint);

  const body = () => ({
    name: f.name.trim(),
    kind: f.kind,
    service: f.service.trim(),
    channel_default: f.channel_default || null,
    product_default: f.product_default.trim() || null,
    config: f.config,
    secret: f.secret,
    enabled: f.enabled,
    schedule_min: PULL.includes(f.kind) ? Math.max(0, Number(f.schedule_min) || 0) : 0,
    rotate_token: !!f.rotate_token,
  });

  async function runTest() {
    const n = ++seq.current;
    let sample: unknown;
    if (f.kind === 'webhook') {
      if (!f.sample.trim()) return setTest(null);
      try {
        sample = JSON.parse(f.sample);
      } catch {
        return setErrs({ sample: t('Пример должен быть JSON: проверьте скобки и кавычки.') });
      }
    }
    setTesting(true);
    // Сохранённый секрет сервер подставляет только в проверку сохранённого источника
    const needsSecret = f.kind === 'org_api' || (f.kind === 'http_json' && f.config.auth_header);
    try {
      const r =
        editing && !f.secret && needsSecret
          ? await send('POST', `/sources/${enc(f.id)}/test`, sample === undefined ? undefined : { sample })
          : await send('POST', '/sources/test', { ...body(), sample });
      if (n === seq.current) {
        setTest(r);
        setErrs({});
      }
    } catch (e: any) {
      if (n === seq.current) {
        setTest({ ok: false, error: e.message, preview: [], errors: [], paths: [] });
        setErrs(e.fields ?? {});
      }
    }
    if (n === seq.current) setTesting(false);
  }

  // Предпросмотр обновляется сам, пока меняются поля сопоставления или пример тела
  const mapKey = JSON.stringify([f.config.mapping, f.config.records_path, f.sample]);
  useEffect(() => {
    if (step === 'check') runTest();
    if (step !== 'fields') return;
    const h = setTimeout(runTest, 500);
    return () => clearTimeout(h);
  }, [step, mapKey]);

  function need(): Fields {
    const e: Fields = {};
    if (step === 'type' && !f.kind) e.kind = t('Выберите вид источника.');
    if (step === 'connect') {
      if (!f.name.trim()) e.name = t('Укажите название: его видно в очереди и отчётах.');
      if (f.kind === 'http_json' && !/^https?:\/\/./.test(f.config.url ?? '')) e['config.url'] = t('Адрес должен начинаться с https:// или http://');
      if (f.kind === 'org_api' && !String(f.config.group_id ?? '').trim()) e['config.group_id'] = t('Укажите group_id.');
    }
    if (step === 'fields')
      for (const [k, , req] of mapFields()) if (req && !String(f.config.mapping?.[k] ?? '').trim()) e[`config.mapping.${k}`] = t('Обязательное поле: укажите путь в записи.');
    return e;
  }
  function next() {
    const e = need();
    setErrs(e);
    if (!Object.keys(e).length) setStep(steps[at + 1][0]);
  }

  async function save() {
    setBusy(true);
    try {
      const out = editing ? await send('PUT', `/sources/${enc(f.id)}`, body()) : await send('POST', '/sources', body());
      onSaved();
      if (out?.token) {
        setToken({ token: out.token, url: ingestUrl(out) });
        setStep('token');
      } else {
        toast(t('Источник «{name}» сохранён.', { name: f.name.trim() }));
        onClose();
      }
    } catch (e: any) {
      const fl: Fields = e.fields ?? {};
      setErrs(fl);
      const k = Object.keys(fl)[0];
      if (k) setStep(k.startsWith('config.mapping') || k === 'sample' ? 'fields' : k === 'kind' ? 'type' : 'connect');
      toast(t('Источник не сохранён: {e}', { e: e.message }));
    }
    setBusy(false);
  }

  async function remove() {
    if (!confirm(t('Удалить источник «{name}»? Это нельзя отменить.', { name: src.name }))) return;
    try {
      await send('DELETE', `/sources/${enc(src.id)}`);
    } catch (e: any) {
      if (e.status !== 409) return toast(t('Источник не удалён: {e}', { e: e.message }));
      if (!confirm(t('{e} Отправить в архив? Диалоги и учёт останутся, источник выключится.', { e: e.message }))) return;
      try {
        await send('DELETE', `/sources/${enc(src.id)}?archive=true`);
      } catch (e2: any) {
        return toast(t('Источник не удалён: {e}', { e: e2.message }));
      }
    }
    toast(t('Источник «{name}» удалён.', { name: src.name }));
    onSaved();
    onClose();
  }

  const k = kinds();
  const paths: string[] = test?.paths ?? [];

  return (
    <Modal open onOpenChange={v => !v && onClose()} title={editing ? t('Изменить источник') : t('Добавить источник')} description={f.kind ? k[f.kind]?.[0] : t('Откуда CQA будет получать диалоги.')} wide>
      {step === 'token' && token ? (
        <div className="flex flex-col gap-4" data-step="token">
          <div className="box ev" role="alert">
            {t('Токен показан один раз. Скопируйте его сейчас и передайте в настройки внешнего сервиса: потом его можно только заменить новым.')}
          </div>
          <CopyField label={t('Адрес webhook')} value={token.url} act="copy-url" />
          <CopyField label={t('Токен')} value={token.token} act="copy-token" />
          <p className="text-xs text-muted">
            {f.config.auth === 'hmac' ? t('Сервис подписывает тело: заголовок X-CQA-Signature: sha256=<HMAC тела по токену>.') : t('Сервис шлёт заголовок Authorization: Bearer <токен>.')}
          </p>
          <div className="flex justify-end">
            <Button variant="primary" data-act="source-done" onClick={onClose}>
              {t('Готово')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <ol className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]" aria-label={t('Шаги')}>
            {steps.map(([s, label], i) => (
              <li key={s} aria-current={s === step ? 'step' : undefined} className={cn(s === step ? 'font-semibold text-ink' : 'text-muted')}>
                {i + 1}. {label}
              </li>
            ))}
          </ol>

          {step === 'type' && (
            <fieldset className="flex flex-col gap-2" data-step="type">
              <legend className="sr">{t('Вид источника')}</legend>
              {NEW_KINDS.map(kind => (
                <label key={kind} className={cn('flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5', f.kind === kind ? 'border-accent bg-accent-soft' : 'border-line hover:bg-hover')}>
                  <input type="radio" name="kind" className="mt-1" checked={f.kind === kind} onChange={() => setF((x: any) => ({ ...x, kind, config: configFor(kind) }))} />
                  <span>
                    <span className="block font-semibold">{k[kind][0]}</span>
                    <span className="block text-[13px] text-muted">{k[kind][1]}</span>
                  </span>
                </label>
              ))}
              {errs.kind && <p className="text-[13px] text-risk">{errs.kind}</p>}
            </fieldset>
          )}

          {step === 'connect' && (
            <div className="grid gap-3 sm:grid-cols-2" data-step="connect">
              <Field label={t('Название')} hint={err('name')}>
                <input className="fld" value={f.name} onChange={e => set('name', e.target.value)} aria-invalid={!!errs.name} autoFocus />
              </Field>
              <Field label={t('Сервис')} hint={err('service', t('Например, Zendesk или колл-центр'))}>
                <input className="fld" value={f.service} onChange={e => set('service', e.target.value)} />
              </Field>
              {f.kind === 'org_api' && (
                <>
                  <Field label="group_id" hint={err('config.group_id')}>
                    <input className="fld" value={f.config.group_id ?? ''} onChange={e => setCfg('group_id', e.target.value)} aria-invalid={!!errs['config.group_id']} />
                  </Field>
                  <Field label={t('Ссылка API организаторов')} hint={err('secret', f.has_secret ? t('Сохранена. Оставьте пустым, чтобы не менять.') : t('Хранится на сервере и после сохранения не показывается.'))}>
                    <input className="fld" type="password" autoComplete="off" value={f.secret} placeholder={f.has_secret ? '••••••' : 'https://…'} onChange={e => set('secret', e.target.value)} aria-invalid={!!errs.secret} />
                  </Field>
                </>
              )}
              {f.kind === 'http_json' && (
                <>
                  <Field label={t('Адрес')} className="sm:col-span-2" hint={err('config.url')}>
                    <input className="fld" value={f.config.url ?? ''} placeholder="https://" onChange={e => setCfg('url', e.target.value)} aria-invalid={!!errs['config.url']} />
                  </Field>
                  <Field label={t('Метод')} hint={err('config.method')}>
                    <select className="fld" value={f.config.method ?? 'GET'} onChange={e => setCfg('method', e.target.value)}>
                      <option>GET</option>
                      <option>POST</option>
                    </select>
                  </Field>
                  <Field label={t('Заголовок авторизации')} hint={err('config.auth_header', t('Имя заголовка, например Authorization. Пусто — без авторизации.'))}>
                    <input className="fld" value={f.config.auth_header ?? ''} onChange={e => setCfg('auth_header', e.target.value)} />
                  </Field>
                  {f.config.auth_header && (
                    <Field label={t('Значение заголовка')} hint={err('secret', f.has_secret ? t('Сохранено. Оставьте пустым, чтобы не менять.') : t('Хранится на сервере и после сохранения не показывается.'))}>
                      <input className="fld" type="password" autoComplete="off" value={f.secret} placeholder={f.has_secret ? '••••••' : ''} onChange={e => set('secret', e.target.value)} aria-invalid={!!errs.secret} />
                    </Field>
                  )}
                </>
              )}
              {f.kind === 'webhook' && (
                <>
                  <Field label={t('Подпись запросов')} hint={err('config.auth')}>
                    <select className="fld" value={f.config.auth ?? 'bearer'} onChange={e => setCfg('auth', e.target.value)}>
                      <option value="bearer">{t('Токен в заголовке Authorization')}</option>
                      <option value="hmac">{t('Подпись HMAC тела запроса')}</option>
                    </select>
                  </Field>
                  {editing && (
                    <>
                      <CopyField label={t('Адрес webhook')} value={ingestUrl(f)} act="copy-url" />
                      <label className="flex items-center gap-2 text-[13px] sm:col-span-2">
                        <input type="checkbox" checked={!!f.rotate_token} onChange={e => set('rotate_token', e.target.checked)} />
                        {t('Выдать новый токен при сохранении: старый перестанет работать')}
                      </label>
                    </>
                  )}
                </>
              )}
              <Field label={t('Канал по умолчанию')} hint={t('Если в записи нет канала')}>
                <select className="fld" value={f.channel_default} onChange={e => set('channel_default', e.target.value)}>
                  <option value="">—</option>
                  <option value="chat">{t('Чат')}</option>
                  <option value="call">{t('Звонок')}</option>
                </select>
              </Field>
              <Field label={t('Продукт по умолчанию')} hint={t('Если в записи нет продукта')}>
                <input className="fld" value={f.product_default} onChange={e => set('product_default', e.target.value)} />
              </Field>
              {PULL.includes(f.kind) && (
                <Field label={t('Синхронизировать каждые, мин')} hint={err('schedule_min', t('0 — только по кнопке «Синхронизировать»'))}>
                  <input className="fld" type="number" min={0} value={f.schedule_min} onChange={e => set('schedule_min', e.target.value)} />
                </Field>
              )}
              <label className="flex items-center gap-2 self-end pb-2.5 text-[13px]">
                <input type="checkbox" checked={f.enabled} onChange={e => set('enabled', e.target.checked)} />
                {t('Источник включён')}
              </label>
            </div>
          )}

          {step === 'fields' && (
            <div className="flex flex-col gap-3" data-step="fields">
              <p className="text-[13px] text-muted">{t('Укажите, где в записи лежит каждое поле: путь вида data.items или agent.name. Предпросмотр обновляется сам.')}</p>
              {f.kind === 'webhook' && (
                <Field label={t('Пример тела запроса (JSON)')} hint={err('sample', t('Вставьте один запрос сервиса, чтобы проверить сопоставление.'))}>
                  <textarea className="fld font-mono text-[13px]" value={f.sample} onChange={e => set('sample', e.target.value)} aria-invalid={!!errs.sample} />
                </Field>
              )}
              <Field label={t('Путь к списку записей')} hint={err('config.records_path', t('Пусто — тело ответа и есть список'))}>
                <input className="fld" value={f.config.records_path ?? ''} onChange={e => setCfg('records_path', e.target.value)} />
              </Field>
              <datalist id="source-paths">
                {paths.map(p => (
                  <option key={p} value={p} />
                ))}
              </datalist>
              <div className="grid gap-3 sm:grid-cols-2">
                {mapFields().map(([key, label, req]) => (
                  <Field key={key} label={req ? `${label} *` : label} hint={err(`config.mapping.${key}`)}>
                    <input className="fld" list="source-paths" value={f.config.mapping?.[key] ?? ''} onChange={e => setMap(key, e.target.value)} aria-invalid={!!errs[`config.mapping.${key}`]} data-map={key} />
                  </Field>
                ))}
              </div>
              <TestResult test={test} testing={testing} />
            </div>
          )}

          {step === 'check' && (
            <div className="flex flex-col gap-3" data-step="check">
              {f.kind === 'webhook' && !f.sample.trim() ? (
                <p className="text-[13px] text-muted">{t('Без примера тела проверить нечего: вернитесь на шаг «Поля» или сохраните без проверки.')}</p>
              ) : (
                <TestResult test={test} testing={testing} />
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-line2 pt-4">
            <div>
              {editing && (
                <Button variant="danger" data-act="source-delete" onClick={remove}>
                  {t('Удалить')}
                </Button>
              )}
            </div>
            <div className="flex gap-2.5">
              {at > (editing ? 1 : 0) && (
                <Button variant="ghost" onClick={() => setStep(steps[at - 1][0])}>
                  {t('Назад')}
                </Button>
              )}
              {step === 'check' ? (
                <>
                  <Button data-act="source-test" disabled={testing} onClick={runTest}>
                    {t('Проверить снова')}
                  </Button>
                  <Button variant="primary" data-act="source-save" disabled={busy} aria-busy={busy} onClick={save}>
                    {busy ? t('Сохраняем…') : t('Сохранить')}
                  </Button>
                </>
              ) : (
                <Button variant="primary" data-act="source-next" onClick={next}>
                  {t('Далее')}
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function TestResult({ test, testing }: { test: any; testing: boolean }) {
  if (testing && !test) return <p className="text-[13px] text-muted">{t('Проверяем связь…')}</p>;
  if (!test) return null;
  if (!test.ok)
    return (
      <div className="box risk" role="alert" data-test-result="error">
        {t('Проверка не прошла: {e}', { e: test.error })}
      </div>
    );
  return (
    <div className="flex flex-col gap-2" data-test-result="ok" aria-busy={testing}>
      <p className="text-[13px]">
        <Chip tone="ok">{t('Связь есть')}</Chip> {t('Записей в ответе: {n}. Первые три диалога после разбора:', { n: test.records })}
      </p>
      {test.preview.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="tbl" aria-label={t('Предпросмотр')}>
            <thead>
              <tr>
                <th>{t('Диалог')}</th>
                <th>{t('Канал')}</th>
                <th>{t('Язык')}</th>
                <th className="num">{t('Реплик')}</th>
                <th>{t('Начало')}</th>
              </tr>
            </thead>
            <tbody>
              {test.preview.map((d: any) => (
                <tr key={d.id}>
                  <td>{d.external_id ?? d.id}</td>
                  <td>{d.ch}</td>
                  <td>{d.lang}</td>
                  <td className="num">{d.lines}</td>
                  <td className="max-w-[280px] truncate text-[13px] text-ink2">{(d.sample ?? []).map((x: any) => `${x.who}: ${x.text}`).join(' / ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {test.errors.length > 0 && (
        <div className="box ev">
          <p className="font-semibold">{t('Не разобраны: {n}', { n: test.errors.length })}</p>
          <ul className="mt-1 list-disc pl-5 text-[13px]">
            {test.errors.map((e: string) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Journal({ src, onClose }: { src: any; onClose: () => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    send('GET', `/sources/${enc(src.id)}/syncs?limit=50`).then(setRows, e => setError(e.message));
  }, [src.id]);
  return (
    <Modal open onOpenChange={v => !v && onClose()} title={t('Журнал синхронизаций')} description={src.name} wide>
      {error ? (
        <div className="box risk">{t('Журнал не загружен: {e}', { e: error })}</div>
      ) : !rows ? (
        <Skeleton className="h-32" />
      ) : !rows.length ? (
        <p className="text-muted">{t('Синхронизаций ещё не было.')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="tbl" aria-label={t('Синхронизации')}>
            <thead>
              <tr>
                <th>{t('Начало')}</th>
                <th>{t('Итог')}</th>
                <th className="num">{t('Добавлено')}</th>
                <th className="num">{t('Пропущено')}</th>
                <th className="num">{t('Длительность')}</th>
                <th>{t('Ошибки')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id ?? r.started}>
                  <td>{when(r.started)}</td>
                  <td>
                    <Chip tone={SYNC[r.status]?.[1] ?? 'na'}>{SYNC[r.status]?.[0]() ?? r.status}</Chip>
                  </td>
                  <td className="num">{r.added}</td>
                  <td className="num">{r.skipped}</td>
                  <td className="num">{r.duration_ms == null ? '—' : t('{s} с', { s: (r.duration_ms / 1000).toFixed(1) })}</td>
                  <td className="max-w-[320px] text-[13px] text-ink2">{r.errors?.length ? r.errors.slice(0, 3).join('; ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

export function Sources(_: { id: string | null }) {
  const [list, setList] = useState<any[] | null>(null);
  const [stats, setStats] = useState<Record<string, any>>({});
  const [error, setError] = useState('');
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [why, setWhy] = useState<string | null>(null);
  const [edit, setEdit] = useState<any>(null);
  const [log, setLog] = useState<any>(null);

  async function load() {
    try {
      const [l, st] = await Promise.all([send('GET', '/sources'), send('GET', '/sources/stats')]);
      setList(l.filter((s: any) => !s.archived));
      setStats(Object.fromEntries(st.map((x: any) => [x.id, x])));
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function sync(s: any) {
    setSyncing(x => ({ ...x, [s.id]: true }));
    try {
      const r = await send('POST', `/sources/${enc(s.id)}/sync`);
      toast(
        r?.status === 'error'
          ? t('Синхронизация «{name}» с ошибкой: {e}', { name: s.name, e: r.errors?.[0] ?? '' })
          : t('Синхронизация «{name}»: добавлено {added}, пропущено {skipped}.', { name: s.name, added: r?.added ?? 0, skipped: r?.skipped ?? 0 }),
      );
      reload();
    } catch (e: any) {
      toast(t('Синхронизация не выполнена: {e}', { e: e.message }));
    }
    setSyncing(x => ({ ...x, [s.id]: false }));
    load();
  }

  const add = () => setEdit({});
  const k = kinds();

  return (
    <>
      <PageHead title={t('Источники данных')} sub={t('Откуда приходят диалоги: здоровье, свежесть и журнал синхронизаций каждого источника.')}>
        {!!list?.length && (
          <Button variant="primary" data-act="source-add" onClick={add}>
            {t('Добавить источник')}
          </Button>
        )}
      </PageHead>
      {error ? (
        <div className="box risk" role="alert">
          {t('Источники не загружены: {e}', { e: error })}
        </div>
      ) : !list ? (
        <Skeleton className="h-48" />
      ) : !list.length ? (
        <Card>
          <Empty
            action={
              <Button variant="primary" data-act="source-add" onClick={add}>
                {t('Добавить источник')}
              </Button>
            }
          >
            {t('Источников пока нет: диалоги загружаются только вручную.')}
          </Empty>
        </Card>
      ) : (
        <Card aria-label={t('Источники')} className="divide-y divide-line2">
          {list.map(s => {
            const st = stats[s.id] ?? {};
            const last = st.last_sync;
            const busy = syncing[s.id] || !!st.running;
            const h = HEALTH[st.health];
            return (
              <article key={s.id} data-source={s.id} className="flex flex-col gap-2.5 px-4 py-3.5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-[15px] font-semibold">{s.name}</h2>
                      {h && (
                        <Chip tone={h[1]} data-health={st.health}>
                          {h[0]()}
                        </Chip>
                      )}
                      {st.basis && (
                        <Button size="sm" variant="ghost" data-act="health-why" aria-expanded={why === s.id} onClick={() => setWhy(why === s.id ? null : s.id)}>
                          {t('Почему')}
                        </Button>
                      )}
                    </div>
                    <p className="text-[13px] text-muted">{[k[s.kind]?.[0] ?? s.kind, s.service].filter(Boolean).join(' · ')}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {PULL.includes(s.kind) && s.enabled && (
                      <Button size="sm" data-act="source-sync" disabled={busy} aria-busy={busy} onClick={() => sync(s)}>
                        {busy ? t('Синхронизируется…') : t('Синхронизировать')}
                      </Button>
                    )}
                    {!BUILTIN.includes(s.kind) && (
                      <Button size="sm" data-act="source-edit" onClick={() => setEdit(s)}>
                        {t('Изменить')}
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" data-act="source-log" onClick={() => setLog(s)}>
                      {t('Журнал')}
                    </Button>
                  </div>
                </div>
                {why === s.id && (
                  <p className="text-[13px] text-ink2" data-basis>
                    {st.basis}
                  </p>
                )}
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-3 lg:grid-cols-6">
                  <div>
                    <dt className="text-muted">{t('Последняя синхронизация')}</dt>
                    <dd>
                      {last ? (
                        <>
                          {when(last.finished ?? last.started)} <span className={cn(last.status === 'error' ? 'text-risk' : last.status === 'partial' ? 'text-ev' : 'text-ink2')}>{SYNC[last.status]?.[0]() ?? last.status}</span>
                          {last.status !== 'error' && <span className="block text-muted">{t('+{added}, пропущено {skipped}', { added: last.added, skipped: last.skipped })}</span>}
                        </>
                      ) : (
                        '—'
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('Диалогов / оценено')}</dt>
                    <dd>
                      {st.dialogs ?? 0} / {st.scored ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('Средний итог')}</dt>
                    <dd>{st.avg_total ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('С грубой ошибкой')}</dt>
                    <dd>{pct(st.gross_share)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('Синхронизаций с ошибкой')}</dt>
                    <dd>{pct(st.error_rate)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t('Новые данные')}</dt>
                    <dd>{ago(st.freshness_s)}</dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </Card>
      )}
      {edit && <Wizard src={edit} onClose={() => setEdit(null)} onSaved={load} />}
      {log && <Journal src={log} onClose={() => setLog(null)} />}
    </>
  );
}
