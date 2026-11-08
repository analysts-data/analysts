// Окно режима оценки по клику на плашку #mode: оценщик, модели OpenAI-формата со своими ключами, основная модель,
// второе мнение, обезличивание, реальные звонки. GET и PUT /api/config, PUT и DELETE /api/providers/{id}, POST …/check.
// Пояснения здесь строкой, не Tip: подсказка Radix рисуется в body, под верхним слоем модального <dialog>.
// По той же причине id модели — в системном title.
import { useEffect, useState } from 'react';
import { configBody, providerBody, risks, whereOf } from '../lib/config.js';
import { t } from '../lib/i18n.js';
import { api, reload, toast } from '../lib/state.js';
import { useS } from '../store';
import { TERMS } from '../terms';
import { Button, Chip, Field } from '../ui';
import { Dlg } from './checklist/Dlg';

const where = (): Record<string, string> => ({ kz: t('в Казахстане'), local: t('локально'), external: t('за рубежом') });
const evaluators = () => [
  ['llm', t('Языковая модель'), t('Ответ, обоснование и цитата по каждому критерию.')],
  ['jev', t('Только Jev (быстро, без обоснований)'), t('Один запрос на диалог: ответы с вероятностью, без цитат; неуверенные уходят на проверку. Нужен ключ Jev.')],
];
const ENV = 'env'; // модель из .env: меняется только там
// название с сервера у модели из .env — слово разработчика, пользователю показываем смысл
const nameOf = (p: any) => (p.id === ENV ? t('Модель по умолчанию (задана на сервере)') : p.label);
// встроенная модель (PR #73): правятся только модель и ключ, DELETE сбрасывает её к исходным настройкам
const BUILTIN = 'openrouter-jev';
const keyHint = (has: boolean) => (has ? t('сохранён; оставьте пустым, чтобы не менять') : t('не задан'));
const fld = 'fld w-full';

export function ModeDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [cfg, setCfg] = useState<any>(null);
  const [edit, setEdit] = useState<any>(null); // модель в форме: объект провайдера или {} для новой
  const [checks, setChecks] = useState<Record<string, { ok: boolean; text: string }>>({});
  const close = () => onOpenChange(false);
  const qa = useS().role === 'qa'; // режим меняет только специалист КК: плашку у других ролей шапка не делает кнопкой

  const load = async () => {
    try {
      setCfg(await api.getConfig());
    } catch (e) {
      toast(t('Режим не загружен: {error}', { error: e.message }));
      close();
    }
  };
  useEffect(() => {
    if (open && qa) load();
    else {
      setCfg(null);
      setEdit(null);
      setChecks({});
    }
  }, [open]);
  if (!open || !cfg || !qa) return null;

  const saveMode = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    const body = configBody({ ...Object.fromEntries(fd), anonymize: fd.has('anonymize'), allow_real_data: fd.has('allow_real_data') });
    const warn = risks(cfg, { ...body, data_where: whereOf(cfg, body.llm_provider) });
    if (warn.length && !confirm(`${warn.join('\n')}\n\n${t('Сохранить режим?')}`)) return close();
    try {
      await api.putConfig(body);
      await reload();
      toast(t('Режим сохранён и применён.'));
      close();
    } catch (e) {
      toast(t('Режим не сохранён: {error}', { error: e.message }));
    }
  };

  const saveProvider = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    try {
      await api.putProvider(fd.get('id'), providerBody(Object.fromEntries(fd)));
      await reload(); // правка основной модели меняет плашку режима
      toast(t('Модель сохранена.'));
      setEdit(null);
      load();
    } catch (e) {
      toast(t('Модель не сохранена: {error}', { error: e.message })); // форма остаётся с введёнными данными
    }
  };

  const del = async (p: any) => {
    const reset = p.id === BUILTIN;
    if (!confirm(reset ? t('Сбросить модель «{label}» к исходным настройкам?', { label: p.label }) : t('Удалить модель «{label}»?', { label: p.label }))) return;
    try {
      await api.deleteProvider(p.id);
      toast(reset ? t('Модель сброшена.') : t('Модель удалена.'));
      load();
    } catch (e) {
      toast(reset ? t('Модель не сброшена: {error}', { error: e.message }) : t('Модель не удалена: {error}', { error: e.message }));
    }
  };

  const check = async (p: any) => {
    toast(t('Проверяем «{label}»…', { label: nameOf(p) }));
    setChecks(c => ({ ...c, [p.id]: { ok: true, text: t('проверяем…') } }));
    let res: { ok: boolean; text: string };
    try {
      const r = await api.checkProvider(p.id);
      res = r.ok ? { ok: true, text: t('отвечает: {ms} мс', { ms: r.ms }) } : { ok: false, text: t('не отвечает: {error}', { error: r.error }) };
    } catch (e) {
      res = { ok: false, text: t('проверка не удалась: {error}', { error: e.message }) };
    }
    setChecks(c => ({ ...c, [p.id]: res }));
    toast(t('«{label}» {result}.', { label: nameOf(p), result: res.text }));
  };

  if (edit) {
    const isNew = !edit.id,
      fixed = edit.id === BUILTIN; // адрес, тип API и место обработки задаёт сервер
    const p = isNew ? { id: '', label: '', base_url: '', model: '', profile: cfg.profiles[0], where: 'external', has_key: false } : edit;
    return (
      <Dlg
        key="provider"
        title={isNew ? t('Новая модель') : t('Модель {label}', { label: p.label })}
        sub={t('Любой OpenAI-совместимый API. Ключ хранится на сервере и в браузер не возвращается.')}
        onClose={close}
        onSubmit={saveProvider}
        footer={
          <>
            <Button value="cancel" onClick={() => setEdit(null)}>
              {t('Назад')}
            </Button>
            <Button type="submit" variant="primary" value="ok">
              {t('Сохранить модель')}
            </Button>
          </>
        }
      >
        <Field label={t('Код')} hint={t('Строчная латиница, цифры, дефис; после создания не меняется.')}>
          <input name="id" className={fld} required pattern="[a-z0-9\-]{1,32}" defaultValue={p.id} readOnly={!isNew} />
        </Field>
        <Field label={t('Название')} hint={t('Так модель называется в списке и на плашке второго мнения.')}>
          <input name="label" className={fld} required defaultValue={p.label} readOnly={fixed} />
        </Field>
        <Field label={t('Адрес API')}>
          <input name="base_url" className={fld} required defaultValue={p.base_url || ''} readOnly={fixed} placeholder={t('https://llm.example/v1 или http://127.0.0.1:11434/v1')} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label={t('Модель')}>
            <input name="model" className={fld} required defaultValue={p.model} />
          </Field>
          <Field label={t('Тип API')}>
            {fixed ? (
              <input name="profile" className={fld} readOnly defaultValue={p.profile} />
            ) : (
              <select name="profile" className={fld} defaultValue={p.profile}>
                {cfg.profiles.map((x: string) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
        <Field label={t('Где обрабатываются данные')} hint={t('Внешний провайдер без обезличивания потребует подтверждения при сохранении режима.')}>
          {fixed ? (
            <>
              <input type="hidden" name="where" value={p.where} />
              <input className={fld} readOnly value={where()[p.where] || p.where} />
            </>
          ) : (
            <select name="where" className={fld} defaultValue={p.where}>
              {Object.entries(where()).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('Ключ API')}>
          <input name="key" type="password" className={fld} autoComplete="off" placeholder={keyHint(p.has_key)} />
        </Field>
      </Dlg>
    );
  }

  const second = [['', t('Выключено')], ['jev', 'Jev'], ...cfg.providers.map((p: any) => [p.id, nameOf(p)])];
  return (
    <Dlg
      key="mode"
      wide
      title={t('Режим оценки')}
      sub={t('Какая модель оценивает диалоги и куда уходят данные. Применяется сразу, без перезапуска сервера. Ключи хранятся на сервере и в браузер не возвращаются.')}
      onClose={close}
      onSubmit={saveMode}
      footer={
        <>
          <Button value="cancel" onClick={close}>
            {t('Отмена')}
          </Button>
          <Button type="submit" variant="primary" value="ok">
            {t('Сохранить режим')}
          </Button>
        </>
      }
    >
      {cfg.llm_mode !== 'live' && (
        <p className="box ev">
          {t('Демо-режим: модель не вызывается, показаны записанные ответы. Настройки подключения ниже не используются.')}
        </p>
      )}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1.5 text-[13px] font-semibold text-ink2">{t('Оценщик')}</legend>
        {evaluators().map(([v, label, hint]) => (
          <label key={v} className="flex items-baseline gap-2 text-sm">
            <input type="radio" name="evaluator" value={v} defaultChecked={v === (cfg.evaluator || 'llm')} />
            <span>
              {label}
              <span className="block text-xs text-muted">{hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1.5 text-[13px] font-semibold text-ink2">{t('Подключённые модели: выберите основную')}</legend>
        {cfg.providers.map((p: any) => (
          <div key={p.id} data-provider={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
            <label className="flex min-w-0 flex-[1_1_260px] items-baseline gap-2">
              <input type="radio" name="llm_provider" value={p.id} defaultChecked={p.id === cfg.llm_provider} />
              <span className="min-w-0">
                <b title={p.model}>{nameOf(p)}</b>{' '}
                <span className="text-muted">
                  {where()[p.where] || p.where} · {!p.has_key ? t('ключ не задан') : p.id === ENV ? t('ключ задан администратором') : t('ключ сохранён')}
                </span>
                {p.id === BUILTIN && !p.has_key && (
                  <Chip tone="ev" className="ml-1.5">
                    {t('Нужен ключ OpenRouter')}
                  </Chip>
                )}
                {p.id === BUILTIN && <span className="block text-xs text-muted">{t('Чат-модель с обоснованиями. Не путать с режимом „Только Jev“ (API TypeSafe с вероятностями).')}</span>}
                {checks[p.id] && (
                  <Chip tone={checks[p.id].ok ? 'ok' : 'risk'} className="ml-1.5">
                    {checks[p.id].text}
                  </Chip>
                )}
              </span>
            </label>
            <span className="flex flex-wrap gap-1.5">
              <Button size="sm" data-act="prov-check" onClick={() => check(p)}>
                {t('Проверить связь')}
              </Button>
              {p.id !== ENV && (
                <>
                  <Button size="sm" data-act="prov-edit" onClick={() => setEdit(p)}>
                    {t('Изменить')}
                  </Button>
                  <Button size="sm" variant={p.id === BUILTIN ? 'default' : 'danger'} data-act="prov-del" onClick={() => del(p)}>
                    {p.id === BUILTIN ? t('Сбросить') : t('Удалить')}
                  </Button>
                </>
              )}
            </span>
          </div>
        ))}
        <div>
          <Button size="sm" data-act="prov-add" onClick={() => setEdit({})}>
            {t('Добавить модель')}
          </Button>
        </div>
      </fieldset>
      <Field label={t('Второе мнение')} hint={`${t(TERMS.second)} ${t('В режиме «Только Jev» не используется.')}`}>
        <select name="verifier" className={fld} defaultValue={cfg.verifier || ''}>
          {second.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t('Ключ Jev')} hint={t('Нужен для режима «Только Jev» и для Jev как второго мнения.')}>
        <input name="jev_api_key" type="password" className={fld} autoComplete="off" placeholder={keyHint(cfg.has_jev_key)} />
      </Field>
      <label className="flex items-baseline gap-2 text-sm">
        <input type="checkbox" name="anonymize" defaultChecked={cfg.anonymize} />
        <span>
          {t('Обезличивать транскрипты перед отправкой модели')}
          <span className="block text-xs text-muted">{t('Имена, телефоны, почта, номера карт, IBAN и ИИН заменяются метками до отправки модели.')}</span>
        </span>
      </label>
      <label className="flex items-baseline gap-2 text-sm">
        <input type="checkbox" name="allow_real_data" defaultChecked={cfg.allow_real_data} />
        <span>
          {t('Разрешить отправлять модели реальные звонки')}
          <span className="block text-xs text-muted">{t('Без отметки реальные звонки модели не отправляются. Включение попросит подтверждение.')}</span>
        </span>
      </label>
    </Dlg>
  );
}
