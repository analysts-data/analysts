// Вставка диалога текстом: окно из очереди, после сохранения карточка открывается, а окно предлагает оценку.
// Окно переживает смену экрана (очередь → карточка), поэтому живёт в своём корне React вне #view.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { href } from '../lib/router.js';
import { canSave } from '../lib/paste.js';
import { t } from '../lib/i18n.js';
import { api, reload, startRun, toast } from '../lib/state.js';
import { Button, Field, Modal } from '../ui';

// Подсказка формата: строки «Роль: текст», строка без роли продолжает предыдущую реплику.
const hint = () => [
  t('Клиент: Здравствуйте, хочу подать заявку на карту'),
  t('Оператор: Добрый день! Как вас зовут?'),
  t('Система: Клиент находится на удержании'),
  '',
  t('Строка без роли продолжает предыдущую реплику.'),
].join('\n');

function PasteDialog({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState('');
  const [ch, setCh] = useState('chat');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [saved, setSaved] = useState<{ id: string; title: string } | null>(null);

  async function save() {
    setBusy(true);
    setErr('');
    let id: string;
    try {
      ({ id } = await api.postPaste({ title: title.trim(), ch, text }));
    } catch (e) {
      setErr(t('Диалог не сохранён: {error}', { error: e.message }));
      setBusy(false);
      return;
    }
    await reload();
    location.hash = href('d', id);
    setSaved({ id, title: title.trim() });
  }

  function evaluate() {
    onClose();
    toast(t('Оценка диалога запущена, прогресс виден в очереди.'));
    startRun({ dialogs: [saved.id], criteria: null });
  }

  return (
    <Modal
      open
      onOpenChange={v => !v && onClose()}
      title={saved ? t('Диалог добавлен') : t('Вставить диалог')}
      description={
        saved
          ? t('«{title}» уже в очереди, карточка открыта. Модель его ещё не оценивала.', { title: saved.title })
          : t('Диалог появится в очереди, и карточка откроется сразу. Оценку запустите кнопкой «Оценить».')
      }
    >
      <form id="dlgForm" className="flex flex-col gap-4" onSubmit={e => e.preventDefault()}>
        {saved ? (
          <>
            <p className="text-[13px] text-muted">{t('Запустить оценку можно и позже из очереди: «Оценить» по видимым диалогам.')}</p>
            <div className="flex justify-end gap-2.5">
              <Button onClick={onClose}>{t('Закрыть')}</Button>
              <Button variant="primary" data-act="prun" data-id={saved.id} onClick={evaluate}>
                {t('Оценить')}
              </Button>
            </div>
          </>
        ) : (
          <>
            <Field label={t('Название')}>
              <input name="title" className="fld" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('Например: обращение из чата поддержки')} autoFocus />
            </Field>
            <Field label={t('Канал')}>
              <select name="ch" className="fld" value={ch} onChange={e => setCh(e.target.value)}>
                <option value="chat">{t('Чат')}</option>
                <option value="call">{t('Звонок')}</option>
              </select>
            </Field>
            <Field label={t('Текст диалога')} hint={t('Каждая реплика с новой строки: «Клиент:», «Оператор:» или «Система:».')}>
              <textarea name="text" className="fld" rows={10} value={text} onChange={e => setText(e.target.value)} placeholder={hint()} />
            </Field>
            <p className="box risk" id="pErr" role="alert" hidden={!err}>
              {err}
            </p>
            <div className="flex flex-wrap items-center justify-end gap-2.5">
              {!canSave(title, text) && <span className="mr-auto text-xs text-muted">{t('Заполните название и текст диалога.')}</span>}
              <Button onClick={onClose}>{t('Отмена')}</Button>
              <Button variant="primary" data-act="psave" disabled={busy || !canSave(title, text)} onClick={save}>
                {busy ? t('Сохраняем…') : t('Сохранить')}
              </Button>
            </div>
          </>
        )}
      </form>
    </Modal>
  );
}

let show: ((n: number) => void) | null = null;
let pending = 0;

/** Хост окна в дереве приложения (app.tsx); без него openPaste создаёт свой корень. */
export function PasteHost() {
  const [n, setN] = useState(pending); // n > 0 — окно открыто; новый n — чистая форма
  show = setN;
  return n ? <PasteDialog key={n} onClose={() => setN(0)} /> : null;
}

/** Открыть окно вставки (кнопка очереди, палитра). */
export function openPaste() {
  pending++;
  if (show) return show(pending);
  const el = document.createElement('div');
  document.body.append(el);
  createRoot(el).render(<PasteHost />);
}
