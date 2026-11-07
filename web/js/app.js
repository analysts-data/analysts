// <cqa-app>: каркас прототипа (сайдбар, верхняя панель, роли, toast, окно), роутинг и делегирование data-act.
import { S, api, cancelRun, init, postDataset, reload, render, resumeRun, toast, uploadDataset } from './state.js';
import { modeText } from './config.js';
import { resolveBase } from './api.js';
import { groupOf } from './queue.js';
import { parseHash } from './router.js';
import * as appealForm from './appeal_form.js';
import * as paste from './views/paste.js';
import * as queue from './views/queue.js';
import * as card from './views/card.js';
import * as appeals from './views/appeals.js';
import * as checklist from './views/checklist.js';
import * as analytics from './views/analytics.js';
import * as coaching from './views/coaching.js';
import { openConfig } from './views/config.js';

// Имя продукта: сайдбар, крошки; <title> в index.html — тем же именем.
const NAME = 'CQA';
// Тот же рисунок, что в ./favicon.svg, но currentColor: на плитке .brand он белый на --accent.
const ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12zM8.3 11.4l2.3 2.3 4.8-4.8-1.3-1.3-3.5 3.5-1-1z"/></svg>';

const VIEWS = { queue, d: card, appeals, checklist, analytics, coaching };
const NAMES = { queue: 'Диалоги', d: 'Карточка разговора', appeals: 'Апелляции', analytics: 'Аналитика', coaching: 'Обучение', checklist: 'Чек-лист' };
const ROLE = { qa: 'специалист КК', operator: 'оператор', reviewer: 'проверяющий' };

const ACTS = Object.assign({
  role: t => { S.role = t.dataset.role; render(); toast(`Роль: ${ROLE[S.role]}.`); },
  cfg: () => openConfig(),
  load: () => postDataset(document.getElementById('gid').value.trim()),
  jsonf: t => { if (t.files[0]) uploadDataset(t.files[0]); t.value = ''; },
  stop: () => cancelRun(),
}, appealForm.actions, paste.actions, ...Object.values(VIEWS).map(v => v.actions || {}));

const SHELL = `
  <aside class="side">
    <div class="brand"><i aria-hidden="true">${ICON}</i><div><b>${NAME}</b><span>Качество диалогов</span></div></div>
    <div class="navgroup">Работа</div>
    <nav class="nav" aria-label="Работа">
      <a href="#/queue" data-page="queue"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>Диалоги<span class="badge" id="bQueue"></span></a>
      <a href="#/appeals" data-page="appeals"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v18M6 21h12M4 7h16M7 7l-3 7c1.5 1.3 4.5 1.3 6 0L7 7zM17 7l-3 7c1.5 1.3 4.5 1.3 6 0l-3-7z"/></svg>Апелляции<span class="badge" id="bAppeals"></span></a>
      <a href="#/coaching" data-page="coaching"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h14v15H6a2 2 0 0 0-2 2V5zM4 20a2 2 0 0 0 2 2h14v-4"/></svg>Обучение</a>
    </nav>
    <div class="navgroup">Обзор и настройка</div>
    <nav class="nav" aria-label="Обзор и настройка">
      <a href="#/analytics" data-page="analytics"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M9 16v-5M14 16V7M19 16v-3"/></svg>Аналитика</a>
      <a href="#/checklist" data-page="checklist"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 5-6"/></svg>Чек-лист</a>
    </nav>
    <div class="sidefoot"><span id="clVer"></span></div>
  </aside>
  <div>
    <header class="top">
      <div class="crumb" id="crumb"></div>
      <div class="row">
        <button type="button" class="mode" id="mode" data-act="cfg" title="Сменить режим оценки: модель, ключи, обезличивание, второе мнение" hidden></button>
        <span class="muted small" id="roleLbl">Роль</span>
        <div class="seg" role="group" aria-labelledby="roleLbl">
          <button type="button" data-act="role" data-role="qa" aria-pressed="true">Специалист КК</button>
          <button type="button" data-act="role" data-role="operator" aria-pressed="false">Оператор</button>
          <button type="button" data-act="role" data-role="reviewer" aria-pressed="false">Проверяющий</button>
        </div>
      </div>
    </header>
    <main id="view" class="content" tabindex="-1"></main>
  </div>
  <dialog id="dlg" aria-labelledby="dlgTitle"><form method="dialog" id="dlgForm"></form></dialog>
  <div id="toast" class="toast" role="status" aria-live="polite" hidden></div>`;

class CqaApp extends HTMLElement {
  connectedCallback() {
    S.app = this;
    init(resolveBase(location.search, this.dataset.api));
    this.innerHTML = SHELL;
    this.view = this.querySelector('#view');
    // click — кнопки и ссылки, change — поля ввода и списки; input — только поля с data-input (на каждый ввод, без перерисовки)
    this.addEventListener('click', e => this.act(e, false));
    this.addEventListener('change', e => this.act(e, true));
    this.addEventListener('input', e => e.target.matches('[data-input]') && this.act(e, true));
    window.addEventListener('hashchange', () => { this.render(true); window.scrollTo(0, 0); });
    if (!location.hash) history.replaceState(null, '', '#/queue');
    this.render();
    reload();
    resumeRun(); // перезагрузка во время оценки: продолжаем опрос запомненного запуска
    // llm_mode задаёт .env и из интерфейса не меняется: хватит одного запроса
    api.getConfig().then(c => { S.llmMode = c.llm_mode; this.render(); }, () => {});
  }

  act(e, fieldEvent) {
    const t = e.target.closest('[data-act]');
    if (!t || t.matches('input, select, textarea') !== fieldEvent) return;
    ACTS[t.dataset.act]?.(t, e);
  }

  render(focusView) {
    const ae = document.activeElement, aid = ae && ae.id, sel = ae && ae.selectionStart;
    const r = S.r = parseHash(location.hash);
    this.dataset.role = S.role;
    this.view.dataset.view = r.page;
    if (S.error) {
      this.view.innerHTML = '<div class="box risk" role="alert"></div>';
      this.view.firstChild.textContent = `Не удалось загрузить данные: ${S.error}`;
    } else {
      this.view.innerHTML = S.loading ? '<div class="card empty">Загрузка данных…</div>' : VIEWS[r.page].view(S, r.id);
    }
    const navPage = r.page === 'd' ? 'queue' : r.page;
    this.querySelectorAll('.nav a').forEach(a => a.dataset.page === navPage ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
    this.querySelector('#crumb').innerHTML = `${NAME} / <b>${NAMES[r.page]}</b>`;
    const mode = this.querySelector('#mode');
    mode.hidden = !S.mode;
    if (S.mode) {
      mode.textContent = modeText(S.mode, S.llmMode);
      mode.classList.toggle('warn', S.mode.where === 'external' || (S.mode.where !== 'local' && !S.mode.anonymized));
    }
    if (S.checklist) {
      this.querySelector('#bQueue').textContent = S.dialogs.filter(d => groupOf(d, S.checklist, S.appeals) !== 'other').length || '';
      this.querySelector('#bAppeals').textContent = S.appeals.filter(a => a.status === 'pending').length || '';
    }
    this.querySelector('#clVer').textContent = S.checklist ? `Чек-лист v${S.checklist.version}` : '';
    this.querySelectorAll('[data-act=role]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.role === S.role)));
    if (focusView) this.view.focus({ preventScroll: true });
    else if (aid) {
      const el = document.getElementById(aid);
      if (el) { el.focus({ preventScroll: true }); try { el.setSelectionRange(sel, sel); } catch { /* не текстовое поле */ } }
    }
  }
}

customElements.define('cqa-app', CqaApp);
