// Окно режима оценки по клику на плашку #mode: оценщик, модели OpenAI-формата со своими ключами, основная модель,
// второе мнение, обезличивание, реальные звонки. GET и PUT /api/config, PUT и DELETE /api/providers/{id}, POST …/check.
import { useEffect, useState } from 'react';
import { configBody, providerBody, risks, whereOf } from '../lib/config.js';
import { api, reload, toast } from '../lib/state.js';
import { Button, Chip, Field } from '../ui';
import { Dlg } from './checklist/Dlg';

const WHERE: Record<string, string> = { kz: 'в Казахстане', local: 'локально', external: 'за рубежом' };
const EVALUATORS = [
  ['llm', 'Языковая модель', 'Ответ, обоснование и цитата по каждому критерию.'],
  ['jev', 'Только Jev (быстро, без обоснований)', 'Один запрос на диалог: ответы с вероятностью, без цитат; неуверенные уходят на проверку. Нужен ключ Jev.'],
];
const ENV = 'env'; // модель из .env: меняется только там
// встроенная модель (PR #73): правятся только модель и ключ, DELETE сбрасывает её к исходным настройкам
const BUILTIN = 'openrouter-jev';
const keyHint = (has: boolean) => (has ? 'сохранён; оставьте пустым, чтобы не менять' : 'не задан');
const fld = 'fld w-full';

export function ModeDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [cfg, setCfg] = useState<any>(null);
  const [edit, setEdit] = useState<any>(null); // модель в форме: объект провайдера или {} для новой
  const [checks, setChecks] = useState<Record<string, { ok: boolean; text: string }>>({});
  const close = () => onOpenChange(false);

  const load = async () => {
    try {
      setCfg(await api.getConfig());
    } catch (e) {
      toast(`Режим не загружен: ${e.message}`);
      close();
    }
  };
  useEffect(() => {
    if (open) load();
    else {
      setCfg(null);
      setEdit(null);
      setChecks({});
    }
  }, [open]);
  if (!open || !cfg) return null;

  const saveMode = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    const body = configBody({ ...Object.fromEntries(fd), anonymize: fd.has('anonymize'), allow_real_data: fd.has('allow_real_data') });
    const warn = risks(cfg, { ...body, data_where: whereOf(cfg, body.llm_provider) });
    if (warn.length && !confirm(`${warn.join('\n')}\n\nСохранить режим?`)) return close();
    try {
      await api.putConfig(body);
      await reload();
      toast('Режим сохранён и применён.');
      close();
    } catch (e) {
      toast(`Режим не сохранён: ${e.message}`);
    }
  };

  const saveProvider = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    try {
      await api.putProvider(fd.get('id'), providerBody(Object.fromEntries(fd)));
      await reload(); // правка основной модели меняет плашку режима
      toast('Модель сохранена.');
      setEdit(null);
      load();
    } catch (e) {
      toast(`Модель не сохранена: ${e.message}`); // форма остаётся с введёнными данными
    }
  };

  const del = async (p: any) => {
    const reset = p.id === BUILTIN;
    if (!confirm(reset ? `Сбросить модель «${p.label}» к исходным настройкам?` : `Удалить модель «${p.label}»?`)) return;
    try {
      await api.deleteProvider(p.id);
      toast(reset ? 'Модель сброшена.' : 'Модель удалена.');
      load();
    } catch (e) {
      toast(`${reset ? 'Модель не сброшена' : 'Модель не удалена'}: ${e.message}`);
    }
  };

  const check = async (p: any) => {
    toast(`Проверяем «${p.label}»…`);
    setChecks(c => ({ ...c, [p.id]: { ok: true, text: 'проверяем…' } }));
    let res: { ok: boolean; text: string };
    try {
      const r = await api.checkProvider(p.id);
      res = r.ok ? { ok: true, text: `отвечает: ${r.ms} мс` } : { ok: false, text: `не отвечает: ${r.error}` };
    } catch (e) {
      res = { ok: false, text: `проверка не удалась: ${e.message}` };
    }
    setChecks(c => ({ ...c, [p.id]: res }));
    toast(`«${p.label}» ${res.text}.`);
  };

  if (edit) {
    const isNew = !edit.id,
      fixed = edit.id === BUILTIN; // адрес, тип API и место обработки задаёт сервер
    const p = isNew ? { id: '', label: '', base_url: '', model: '', profile: cfg.profiles[0], where: 'external', has_key: false } : edit;
    return (
      <Dlg
        key="provider"
        title={isNew ? 'Новая модель' : `Модель ${p.label}`}
        sub="Любой OpenAI-совместимый API. Ключ хранится на сервере и в браузер не возвращается."
        onClose={close}
        onSubmit={saveProvider}
        footer={
          <>
            <Button value="cancel" onClick={() => setEdit(null)}>
              Назад
            </Button>
            <Button type="submit" variant="primary" value="ok">
              Сохранить модель
            </Button>
          </>
        }
      >
        <Field label="Код" hint="Строчная латиница, цифры, дефис; после создания не меняется.">
          <input name="id" className={fld} required pattern="[a-z0-9\-]{1,32}" defaultValue={p.id} readOnly={!isNew} />
        </Field>
        <Field label="Название" hint="Так модель называется в списке и на плашке второго мнения.">
          <input name="label" className={fld} required defaultValue={p.label} readOnly={fixed} />
        </Field>
        <Field label="Адрес API">
          <input name="base_url" className={fld} required defaultValue={p.base_url || ''} readOnly={fixed} placeholder="https://llm.example/v1 или http://127.0.0.1:11434/v1" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="Модель">
            <input name="model" className={fld} required defaultValue={p.model} />
          </Field>
          <Field label="Тип API">
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
        <Field label="Где обрабатываются данные" hint="Внешний провайдер без обезличивания потребует подтверждения при сохранении режима.">
          {fixed ? (
            <>
              <input type="hidden" name="where" value={p.where} />
              <input className={fld} readOnly value={WHERE[p.where] || p.where} />
            </>
          ) : (
            <select name="where" className={fld} defaultValue={p.where}>
              {Object.entries(WHERE).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Ключ API">
          <input name="key" type="password" className={fld} autoComplete="off" placeholder={keyHint(p.has_key)} />
        </Field>
      </Dlg>
    );
  }

  const second = [['', 'нет'], ['jev', 'Jev'], ...cfg.providers.map((p: any) => [p.id, p.label])];
  return (
    <Dlg
      key="mode"
      wide
      title="Режим оценки"
      sub="Применяется сразу, без перезапуска сервера. Ключи хранятся на сервере и в браузер не возвращаются."
      onClose={close}
      onSubmit={saveMode}
      footer={
        <>
          <Button value="cancel" onClick={close}>
            Отмена
          </Button>
          <Button type="submit" variant="primary" value="ok">
            Сохранить режим
          </Button>
        </>
      }
    >
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1.5 text-[13px] font-semibold text-ink2">Оценщик</legend>
        {EVALUATORS.map(([v, t, hint]) => (
          <label key={v} className="flex items-baseline gap-2 text-sm">
            <input type="radio" name="evaluator" value={v} defaultChecked={v === (cfg.evaluator || 'llm')} />
            <span>
              {t}
              <span className="block text-xs text-muted">{hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1.5 text-[13px] font-semibold text-ink2">Модели OpenAI-формата · отметьте основную</legend>
        {cfg.providers.map((p: any) => (
          <div key={p.id} data-provider={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
            <label className="flex min-w-0 flex-[1_1_260px] items-baseline gap-2">
              <input type="radio" name="llm_provider" value={p.id} defaultChecked={p.id === cfg.llm_provider} />
              <span className="min-w-0">
                <b>{p.label}</b>{' '}
                <span className="text-muted">
                  {p.model} · {WHERE[p.where] || p.where} · ключ {p.has_key ? 'есть' : 'не задан'}
                  {p.id === ENV && ' · из .env, меняется только там'}
                </span>
                {p.id === BUILTIN && !p.has_key && (
                  <Chip tone="ev" className="ml-1.5">
                    Нужен ключ OpenRouter
                  </Chip>
                )}
                {p.id === BUILTIN && <span className="block text-xs text-muted">Чат-модель с обоснованиями. Не путать с режимом „Только Jev“ (API TypeSafe с вероятностями).</span>}
                {checks[p.id] && (
                  <Chip tone={checks[p.id].ok ? 'ok' : 'risk'} className="ml-1.5">
                    {checks[p.id].text}
                  </Chip>
                )}
              </span>
            </label>
            <span className="flex flex-wrap gap-1.5">
              <Button size="sm" data-act="prov-check" title="Один короткий запрос без реальных данных" onClick={() => check(p)}>
                Проверить связь
              </Button>
              {p.id !== ENV && (
                <>
                  <Button size="sm" data-act="prov-edit" onClick={() => setEdit(p)}>
                    Изменить
                  </Button>
                  <Button size="sm" variant={p.id === BUILTIN ? 'default' : 'danger'} data-act="prov-del" title={p.id === BUILTIN ? 'Вернуть исходные настройки' : undefined} onClick={() => del(p)}>
                    {p.id === BUILTIN ? 'Сбросить' : 'Удалить'}
                  </Button>
                </>
              )}
            </span>
          </div>
        ))}
        <div>
          <Button size="sm" data-act="prov-add" onClick={() => setEdit({})}>
            Добавить модель
          </Button>
        </div>
      </fieldset>
      <Field label="Второе мнение" hint="Ещё один ответ на диалог; расхождения уходят в «Нужна проверка». В режиме «Только Jev» не используется.">
        <select name="verifier" className={fld} defaultValue={cfg.verifier || ''}>
          {second.map(([v, t]) => (
            <option key={v} value={v}>
              {t}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Ключ Jev" hint="Нужен для режима «Только Jev» и для Jev как второго мнения.">
        <input name="jev_api_key" type="password" className={fld} autoComplete="off" placeholder={keyHint(cfg.has_jev_key)} />
      </Field>
      <label className="flex items-baseline gap-2 text-sm">
        <input type="checkbox" name="anonymize" defaultChecked={cfg.anonymize} />
        <span>
          Обезличивать транскрипты перед отправкой модели
          <span className="block text-xs text-muted">Имена, телефоны, почта, номера карт, IBAN и ИИН заменяются метками до запроса.</span>
        </span>
      </label>
      <label className="flex items-baseline gap-2 text-sm">
        <input type="checkbox" name="allow_real_data" defaultChecked={cfg.allow_real_data} />
        <span>
          Разрешить отправлять модели реальные звонки
          <span className="block text-xs text-muted">Без отметки реальные звонки модели не отправляются. Включение попросит подтверждение.</span>
        </span>
      </label>
      {cfg.llm_mode !== 'live' && <p className="box ev">Сервер запущен в режиме {cfg.llm_mode}: модель отвечает записанными ответами, адрес и ключ не используются.</p>}
    </Dlg>
  );
}
