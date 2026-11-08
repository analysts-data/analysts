// Окно режима оценки по клику на плашку режима: модели OpenAI-формата со своими ключами, основная модель,
// второе мнение. GET /api/config, PUT /api/config, PUT и DELETE /api/providers/{id}, POST …/check.
import { api, reload, toast } from '../state.js';
import { configBody, providerBody, risks, whereOf } from '../config.js';
import { esc } from '../format.js';

const WHERE = { kz: 'в Казахстане', local: 'локально', external: 'за рубежом' };
const EVALUATORS = [['llm', 'Языковая модель'], ['jev', 'Только Jev (быстро, без обоснований)']];
const keyHint = has => (has ? 'сохранён; оставьте пустым, чтобы не менять' : 'не задан');
const ENV = 'env'; // модель из .env: меняется только там
const options = (pairs, current) =>
  pairs.map(([v, t]) => `<option value="${esc(v)}"${v === current ? ' selected' : ''}>${esc(t)}</option>`).join('');

export async function openConfig() {
  let cfg;
  try {
    cfg = await api.getConfig();
  } catch (e) {
    toast(`Режим не загружен: ${e.message}`);
    return;
  }
  const dlg = document.getElementById('dlg'), form = document.getElementById('dlgForm');
  const row = p => `<div class="row small" data-provider="${esc(p.id)}" style="gap:6px">
      <label style="flex:1 1 240px;display:flex;gap:8px;align-items:baseline"><input type="radio" name="llm_provider" value="${esc(p.id)}"${p.id === cfg.llm_provider ? ' checked' : ''}>
        <span><b>${esc(p.label)}</b> <span class="muted">${esc(p.model)} · ${WHERE[p.where] || esc(p.where)} · ключ ${p.has_key ? 'есть' : 'не задан'}</span></span></label>
      <span class="row" style="gap:6px;flex-wrap:nowrap"><button type="button" class="btn sm" data-act="prov-check">Проверить</button>
      ${p.id === ENV ? '' : '<button type="button" class="btn sm" data-act="prov-edit">Изменить</button><button type="button" class="btn sm" data-act="prov-del">Удалить</button>'}</span>
    </div>`;
  const second = [['', 'нет'], ['jev', 'Jev'], ...cfg.providers.map(p => [p.id, p.label])];
  form.innerHTML = `<header><h2 class="h2" id="dlgTitle">Режим оценки</h2><p class="muted small">Применяется сразу, без перезапуска сервера. Ключи хранятся на сервере и в браузер не возвращаются.</p></header>
    <fieldset class="stack" style="border:0;padding:0;margin:0;gap:6px"><legend class="label">Оценщик</legend>
      ${EVALUATORS.map(([v, t]) => `<label class="row small"><input type="radio" name="evaluator" value="${v}"${v === (cfg.evaluator || 'llm') ? ' checked' : ''}> ${t}</label>`).join('')}</fieldset>
    <fieldset class="stack" style="border:0;padding:0;margin:0;gap:6px"><legend class="label">Модели OpenAI-формата · отметьте основную модель</legend>
      ${cfg.providers.map(row).join('')}
      <div><button type="button" class="btn sm" data-act="prov-add">Добавить модель</button></div></fieldset>
    <label class="field"><span>Второе мнение: ещё один ответ на диалог, расхождения уходят на проверку</span><select name="verifier" class="fld">${options(second, cfg.verifier || '')}</select></label>
    <label class="field"><span>Ключ Jev</span><input name="jev_api_key" type="password" class="fld" autocomplete="off" placeholder="${keyHint(cfg.has_jev_key)}"></label>
    <label class="row small"><input type="checkbox" name="anonymize"${cfg.anonymize ? ' checked' : ''}> Обезличивать транскрипты перед отправкой модели</label>
    <label class="row small"><input type="checkbox" name="allow_real_data"${cfg.allow_real_data ? ' checked' : ''}> Разрешить отправлять модели реальные звонки</label>
    ${cfg.llm_mode === 'live' ? '' : `<p class="box ev small">Сервер запущен в режиме ${esc(cfg.llm_mode)}: модель отвечает записанными ответами, адрес и ключ не используются.</p>`}
    <footer><button class="btn" value="cancel" formnovalidate>Отмена</button><button class="btn pri" value="ok">Сохранить режим</button></footer>`;
  form.onclick = e => {
    const b = e.target.closest('[data-act^="prov-"]');
    const p = cfg.providers.find(x => x.id === b?.closest('[data-provider]')?.dataset.provider);
    if (b) ({ 'prov-add': () => editProvider(cfg), 'prov-edit': () => editProvider(cfg, p), 'prov-del': () => deleteProvider(p), 'prov-check': () => checkProvider(p) })[b.dataset.act]();
  };
  dlg.returnValue = '';
  dlg.onclose = async () => {
    dlg.onclose = form.onclick = null;
    if (dlg.returnValue !== 'ok') return;
    const fd = new FormData(form);
    const body = configBody({ ...Object.fromEntries(fd), anonymize: fd.has('anonymize'), allow_real_data: fd.has('allow_real_data') });
    const warn = risks(cfg, { ...body, data_where: whereOf(cfg, body.llm_provider) });
    if (warn.length && !confirm(`${warn.join('\n')}\n\nСохранить режим?`)) return;
    try {
      await api.putConfig(body);
      await reload();
      toast('Режим сохранён и применён.');
    } catch (e) {
      toast(`Режим не сохранён: ${e.message}`);
    }
  };
  if (!dlg.open) dlg.showModal();
}

// Форма модели в том же окне; после сохранения или «Назад» — снова окно режима.
function editProvider(cfg, p) {
  const dlg = document.getElementById('dlg'), form = document.getElementById('dlgForm'), isNew = !p;
  p = p || { id: '', label: '', base_url: '', model: '', profile: cfg.profiles[0], where: 'external', has_key: false };
  form.onclick = null;
  form.innerHTML = `<header><h2 class="h2" id="dlgTitle">${isNew ? 'Новая модель' : `Модель ${esc(p.label)}`}</h2><p class="muted small">Любой OpenAI-совместимый API. Ключ хранится на сервере и в браузер не возвращается.</p></header>
    <label class="field"><span>Код: строчная латиница, цифры, дефис</span><input name="id" class="fld" required pattern="[a-z0-9\\-]{1,32}" value="${esc(p.id)}"${isNew ? '' : ' readonly'}></label>
    <label class="field"><span>Название</span><input name="label" class="fld" required value="${esc(p.label)}"></label>
    <label class="field"><span>Адрес API</span><input name="base_url" class="fld" required value="${esc(p.base_url || '')}" placeholder="https://llm.example/v1 или http://127.0.0.1:11434/v1"></label>
    <div class="row" style="gap:10px;align-items:end"><label class="field" style="flex:1"><span>Модель</span><input name="model" class="fld" required value="${esc(p.model)}"></label>
      <label class="field"><span>Тип API</span><select name="profile" class="fld">${options(cfg.profiles.map(x => [x, x]), p.profile)}</select></label></div>
    <label class="field"><span>Где обрабатываются данные</span><select name="where" class="fld">${options(Object.entries(WHERE), p.where)}</select></label>
    <label class="field"><span>Ключ API</span><input name="key" type="password" class="fld" autocomplete="off" placeholder="${keyHint(p.has_key)}"></label>
    <footer><button class="btn" value="cancel" formnovalidate>Назад</button><button class="btn pri" value="ok">Сохранить модель</button></footer>`;
  dlg.returnValue = '';
  dlg.onclose = async () => {
    dlg.onclose = null;
    if (dlg.returnValue === 'ok') {
      const fd = new FormData(form);
      try {
        await api.putProvider(fd.get('id'), providerBody(Object.fromEntries(fd)));
        await reload(); // правка основной модели меняет плашку режима
        toast('Модель сохранена.');
      } catch (e) {
        toast(`Модель не сохранена: ${e.message}`);
      }
    }
    openConfig();
  };
}

async function deleteProvider(p) {
  if (!confirm(`Удалить модель «${p.label}»?`)) return;
  try {
    await api.deleteProvider(p.id);
    toast('Модель удалена.');
    openConfig();
  } catch (e) {
    toast(`Модель не удалена: ${e.message}`);
  }
}

async function checkProvider(p) {
  toast(`Проверяем «${p.label}»…`);
  try {
    const r = await api.checkProvider(p.id);
    toast(r.ok ? `«${p.label}» отвечает: ${r.ms} мс.` : `«${p.label}» не отвечает: ${r.error}`);
  } catch (e) {
    toast(`Проверка не удалась: ${e.message}`);
  }
}
