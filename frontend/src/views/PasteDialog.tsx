// Вставка диалога текстом: окно из очереди, после сохранения карточка открывается, а окно предлагает оценку.
// Окно переживает смену экрана (очередь → карточка), поэтому живёт в своём корне React вне #view.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { href } from '../lib/router.js';
import { canSave } from '../lib/paste.js';
import { api, reload, startRun, toast } from '../lib/state.js';
import { Button, Field, Modal } from '../ui';

// Подсказка формата: строки «Роль: текст», строка без роли продолжает предыдущую реплику.
const HINT = [
  'Клиент: Здравствуйте, хочу подать заявку на карту',
  'Оператор: Добрый день! Как вас зовут?',
  'Система: Клиент находится на удержании',
  '',
  'Строка без роли продолжает предыдущую реплику.',
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
      setErr(`Диалог не сохранён: ${e.message}`);
      setBusy(false);
      return;
    }
    await reload();
    location.hash = href('d', id);
    setSaved({ id, title: title.trim() });
  }

  function evaluate() {
    onClose();
    toast('Оценка диалога запущена, прогресс виден в очереди.');
    startRun({ dialogs: [saved.id], criteria: null });
  }

  return (
    <Modal
      open
      onOpenChange={v => !v && onClose()}
      title={saved ? 'Диалог добавлен' : 'Вставить диалог'}
      description={
        saved
          ? `«${saved.title}» уже в очереди, карточка открыта. Модель его ещё не оценивала.`
          : 'Диалог появится в очереди, и карточка откроется сразу. Оценку запустите кнопкой «Оценить».'
      }
    >
      <form id="dlgForm" className="flex flex-col gap-4" onSubmit={e => e.preventDefault()}>
        {saved ? (
          <>
            <p className="text-[13px] text-muted">Запустить оценку можно и позже из очереди: «Оценить» по видимым диалогам.</p>
            <div className="flex justify-end gap-2.5">
              <Button onClick={onClose}>Закрыть</Button>
              <Button variant="primary" data-act="prun" data-id={saved.id} onClick={evaluate}>
                Оценить
              </Button>
            </div>
          </>
        ) : (
          <>
            <Field label="Название">
              <input name="title" className="fld" value={title} onChange={e => setTitle(e.target.value)} placeholder="Например: обращение из чата поддержки" autoFocus />
            </Field>
            <Field label="Канал">
              <select name="ch" className="fld" value={ch} onChange={e => setCh(e.target.value)}>
                <option value="chat">Чат</option>
                <option value="call">Звонок</option>
              </select>
            </Field>
            <Field label="Текст диалога" hint="Каждая реплика с новой строки: «Клиент:», «Оператор:» или «Система:».">
              <textarea name="text" className="fld" rows={10} value={text} onChange={e => setText(e.target.value)} placeholder={HINT} />
            </Field>
            <p className="box risk" id="pErr" role="alert" hidden={!err}>
              {err}
            </p>
            <div className="flex flex-wrap items-center justify-end gap-2.5">
              {!canSave(title, text) && <span className="mr-auto text-xs text-muted">Заполните название и текст диалога.</span>}
              <Button onClick={onClose}>Отмена</Button>
              <Button variant="primary" data-act="psave" disabled={busy || !canSave(title, text)} onClick={save}>
                {busy ? 'Сохраняем…' : 'Сохранить'}
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
