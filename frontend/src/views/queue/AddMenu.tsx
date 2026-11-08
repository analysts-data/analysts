// «Добавить диалоги»: меню из трёх пунктов (набор организаторов, файл JSON, текст диалога). Только специалисту КК.
// В пустой очереди те же три способа видны сразу (AddChoices).
import { ChevronDown, Plus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { t } from '../../lib/i18n.js';
import { postDataset, saveSource, uploadDataset } from '../../lib/state.js';
import { Button, Field, Modal } from '../../ui';
import { openPaste } from '../PasteDialog';

/** Файл JSON: поле живёт вне меню, иначе меню закроется раньше, чем браузер вернёт файл. */
export function JsonInput() {
  return (
    <input
      id="jsonf"
      type="file"
      accept="application/json"
      className="sr"
      data-act="jsonf"
      tabIndex={-1}
      onChange={e => {
        const f = e.target.files?.[0];
        e.target.value = '';
        if (f) uploadDataset(f);
      }}
    />
  );
}

function DatasetDialog({ onClose }: { onClose: () => void }) {
  const gid = useRef<HTMLInputElement>(null);
  const url = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  async function load(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const u = url.current.value.trim();
    // ссылка сохраняется на сервере и включает автосинхронизацию; итог загрузки — в toast
    await (u ? saveSource(u, gid.current.value) : postDataset(gid.current.value));
    onClose();
  }
  return (
    <Modal
      open
      onOpenChange={v => !v && onClose()}
      title={t('Набор организаторов')}
      description={t('Диалоги загрузятся по коду набора. Со ссылкой API набор обновляется раз в 5 минут.')}
    >
      <form className="flex flex-col gap-4" onSubmit={load}>
        <Field label={t('Код набора')} hint={t('например, DEV')}>
          <input id="gid" ref={gid} className="fld" defaultValue="DEV" required autoFocus />
        </Field>
        <Field label={t('Ссылка API, необязательно')}>
          <input id="orgurl" ref={url} type="url" className="fld" autoComplete="off" />
        </Field>
        <div className="flex justify-end gap-2.5">
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button type="submit" variant="primary" data-act="load" disabled={busy}>
            {busy ? t('Получаем…') : t('Получить набор')}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** Пустая очередь: три способа добавить диалоги строками, без меню; основной — набор организаторов. */
export function AddChoices() {
  const [dataset, setDataset] = useState(false);
  const rows: [string, string, React.ReactNode][] = [
    [
      t('Набор организаторов'),
      t('По коду набора, например DEV. Со ссылкой API набор обновляется раз в 5 минут.'),
      <Button variant="primary" onClick={() => setDataset(true)}>
        {t('Получить набор')}
      </Button>,
    ],
    [
      t('Файл JSON'),
      t('Выгрузка диалогов в формате организаторов.'),
      <Button onClick={() => document.getElementById('jsonf')?.click()}>{t('Выбрать файл')}</Button>,
    ],
    [
      t('Текст диалога'),
      t('Вставьте переписку из чата или расшифровку звонка: реплики и роли разберутся сами.'),
      <Button data-act="paste" onClick={openPaste}>
        {t('Вставить текст')}
      </Button>,
    ],
  ];
  return (
    <>
      <ul className="divide-y divide-line2">
        {rows.map(([title, sub, action]) => (
          <li key={title} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-4">
            <div className="min-w-0 flex-1 basis-64">
              <p className="font-semibold">{title}</p>
              <p className="text-[13px] text-muted">{sub}</p>
            </div>
            {action}
          </li>
        ))}
      </ul>
      {dataset && <DatasetDialog onClose={() => setDataset(false)} />}
    </>
  );
}

export function AddMenu({ primary }: { primary?: boolean }) {
  const [open, setOpen] = useState(false);
  const [dataset, setDataset] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  const item = 'flex w-full cursor-pointer items-center rounded-md px-3 py-2 text-left text-sm text-ink hover:bg-hover';
  return (
    <div className="relative" ref={ref}>
      <Button variant={primary ? 'primary' : 'default'} aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)}>
        <Plus size={16} aria-hidden="true" /> {t('Добавить диалоги')} <ChevronDown size={16} aria-hidden="true" />
      </Button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 flex w-64 flex-col rounded-lg border border-line bg-surface p-1 shadow-card">
          <button
            type="button"
            className={item}
            onClick={() => {
              setOpen(false);
              setDataset(true);
            }}
          >
            {t('Набор организаторов…')}
          </button>
          <label htmlFor="jsonf" className={item} onClick={() => setTimeout(() => setOpen(false))}>
            {t('Файл JSON…')}
          </label>
          <button
            type="button"
            className={item}
            data-act="paste"
            onClick={() => {
              setOpen(false);
              openPaste();
            }}
          >
            {t('Вставить текст диалога…')}
          </button>
        </div>
      )}
      {dataset && <DatasetDialog onClose={() => setDataset(false)} />}
    </div>
  );
}
