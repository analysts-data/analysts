// Окно режима оценки по клику на плашку режима: GET /api/config, затем PUT /api/config.
import { api, reload, toast } from '../state.js';
import { PRESETS, configBody, presetOf, risks } from '../config.js';
import { esc } from '../format.js';

const WHERE = [['kz', 'в Казахстане'], ['external', 'за рубежом']];
const keyHint = has => (has ? 'сохранён; оставьте пустым, чтобы не менять' : 'не задан');

export async function openConfig() {
  let cfg;
  try {
    cfg = await api.getConfig();
  } catch (e) {
    toast(`Режим не загружен: ${e.message}`);
    return;
  }
  const dlg = document.getElementById('dlg'), form = document.getElementById('dlgForm'), preset = presetOf(cfg);
  form.innerHTML = `<header><h2 class="h2" id="dlgTitle">Режим оценки</h2><p class="muted small">Применяется сразу, без перезапуска сервера. Ключи хранятся на сервере и в браузер не возвращаются.</p></header>
    <fieldset class="stack" style="border:0;padding:0;margin:0;gap:6px"><legend class="label">Где работает модель</legend>
      ${Object.entries(PRESETS).map(([k, label]) => `<label class="row small"><input type="radio" name="preset" value="${k}"${k === preset ? ' checked' : ''}> ${esc(label)}</label>`).join('')}</fieldset>
    <label class="field"><span>Провайдер внешнего API находится</span><select name="where" class="fld">${WHERE.map(([v, t]) => `<option value="${v}"${cfg.data_where === v ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
    <label class="field"><span>Адрес API модели (OpenAI-совместимый)</span><input name="llm_base_url" class="fld" required value="${esc(cfg.llm_base_url || '')}" placeholder="https://llm.example/v1 или http://127.0.0.1:11434/v1"></label>
    <div class="row" style="gap:10px;align-items:end"><label class="field" style="flex:1"><span>Модель</span><input name="llm_model" class="fld" required value="${esc(cfg.llm_model)}"></label>
      <label class="field"><span>Тип API</span><select name="llm_profile" class="fld">${cfg.profiles.map(p => `<option${p === cfg.llm_profile ? ' selected' : ''}>${esc(p)}</option>`).join('')}</select></label></div>
    <label class="field"><span>Ключ API модели</span><input name="llm_api_key" type="password" class="fld" autocomplete="off" placeholder="${keyHint(cfg.has_llm_key)}"></label>
    <label class="row small"><input type="checkbox" name="jev"${cfg.verifier === 'jev' ? ' checked' : ''}> Второе мнение Jev: ещё один запрос на диалог, расхождения уходят на проверку</label>
    <label class="field"><span>Ключ Jev</span><input name="jev_api_key" type="password" class="fld" autocomplete="off" placeholder="${keyHint(cfg.has_jev_key)}"></label>
    <label class="row small"><input type="checkbox" name="allow_real_data"${cfg.allow_real_data ? ' checked' : ''}> Разрешить отправлять модели реальные звонки</label>
    ${cfg.llm_mode === 'live' ? '' : `<p class="box ev small">Сервер запущен в режиме ${esc(cfg.llm_mode)}: модель отвечает записанными ответами, адрес и ключ не используются.</p>`}
    <footer><button class="btn" value="cancel" formnovalidate>Отмена</button><button class="btn pri" value="ok">Сохранить режим</button></footer>`;
  dlg.returnValue = '';
  dlg.onclose = async () => {
    dlg.onclose = null;
    if (dlg.returnValue !== 'ok') return;
    const fd = new FormData(form);
    const fields = { ...Object.fromEntries(fd), jev: fd.has('jev'), allow_real_data: fd.has('allow_real_data') };
    const body = configBody(fd.get('preset'), fd.get('where'), fields);
    const warn = risks(cfg, body);
    if (warn.length && !confirm(`${warn.join('\n')}\n\nСохранить режим?`)) return;
    try {
      await api.putConfig(body);
      await reload();
      toast('Режим сохранён и применён.');
    } catch (e) {
      toast(`Режим не сохранён: ${e.message}`);
    }
  };
  dlg.showModal();
}
