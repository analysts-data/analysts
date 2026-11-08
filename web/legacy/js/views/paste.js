// Вставка нового диалога текстом: кнопка в очереди, модальное окно, карточка и запуск оценки из окна.
import { S, api, reload, startRun, toast } from '../state.js';
import { esc } from '../format.js';
import { href } from '../router.js';

// Подсказка формата в поле: строки «Роль: текст», строка без роли продолжает предыдущую реплику.
const HINT = [
  'Клиент: Здравствуйте, хочу подать заявку на карту',
  'Оператор: Добрый день! Как вас зовут?',
  'Система: Клиент находится на удержании',
  '',
  'Строка без роли продолжает предыдущую реплику.',
].join('\n');

export const canSave = (title, text) => !!(title.trim() && text.trim());

export function openPaste() {
  const form = S.app.querySelector('#dlgForm');
  form.innerHTML = `<header><h2 class="h2" id="dlgTitle">Вставить диалог</h2>
      <p class="muted small">Диалог появится в очереди, карточка откроется сразу — оценку запустите кнопкой «Оценить».</p></header>
    <label class="field"><span>Название</span><input name="title" class="fld" data-act="pcheck" data-input placeholder="Например: обращение из чата поддержки"></label>
    <label class="field"><span>Канал</span><select name="ch" class="fld"><option value="chat">Чат</option><option value="call">Звонок</option></select></label>
    <label class="field"><span>Текст диалога</span><textarea name="text" class="fld" rows="10" data-act="pcheck" data-input placeholder="${esc(HINT)}"></textarea></label>
    <p class="box risk" id="pErr" role="alert" hidden></p>
    <footer><button class="btn" value="cancel" formnovalidate>Отмена</button>
      <button type="button" class="btn pri" data-act="psave" disabled>Сохранить</button></footer>`;
  form.closest('dialog').showModal();
}

export const actions = {
  paste: () => openPaste(),
  pcheck: t => { t.form.querySelector('[data-act="psave"]').disabled = !canSave(t.form.elements.title.value, t.form.elements.text.value); },
  psave: async t => {
    const f = t.form;
    const title = f.elements.title.value.trim();
    t.disabled = true;
    let id;
    try {
      ({ id } = await api.postPaste({ title, ch: f.elements.ch.value, text: f.elements.text.value }));
    } catch (e) {
      const err = f.querySelector('#pErr');
      err.textContent = `Диалог не сохранён: ${e.message}`;
      err.hidden = false;
      t.disabled = false;
      return;
    }
    await reload();
    location.hash = href('d', id);
    f.innerHTML = `<header><h2 class="h2" id="dlgTitle">Диалог добавлен</h2>
      <p class="muted small">«${esc(title)}» уже в очереди, карточка открыта. Модель его ещё не оценивала.</p></header>
    <p class="box na">Запустить оценку можно и позже из очереди: «Оценить» по видимым диалогам.</p>
    <footer><button class="btn" value="cancel" formnovalidate>Позже</button>
      <button type="button" class="btn pri" data-act="prun" data-id="${esc(id)}">Оценить</button></footer>`;
  },
  prun: t => {
    t.closest('dialog').close();
    toast('Оценка диалога запущена, прогресс — в очереди.');
    startRun({ dialogs: [t.dataset.id], criteria: null });
  },
};
