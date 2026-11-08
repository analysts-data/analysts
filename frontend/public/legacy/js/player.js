// Плеер звонка: один настоящий <audio preload="none"> на /api/dialogs/{id}/audio, волна по репликам, переход к моменту.
// Элемент живёт вне #view: перерисовка карточки (раскрытие критерия) не прерывает воспроизведение.
import { S, api, toast } from './state.js';
import { esc, mmss } from './format.js';
import { parseHash } from './router.js';

let audio = null, dialog = null;


const spoken = l => !l.fold && l.s != null;
const folds = d => d.lines.filter(l => l.fold);

// Реплика, которая звучит в момент t: последняя начавшаяся, вне свёрнутых участков.
function lineAt(d, t) {
  if (folds(d).some(f => t >= f.t0 && t < f.t1)) return null;
  let cur = null;
  for (const l of d.lines) if (spoken(l) && l.s <= t) cur = l;
  return cur;
}

// Класс полосы волны: wi — не оценивается (fold, seg internal/after), wc — клиент, wo — оператор, ws — тишина.
function kindAt(d, t) {
  if (folds(d).some(f => t >= f.t0 && t < f.t1)) return 'wi';
  const l = lineAt(d, t);
  if (!l) return 'ws';
  if (l.seg === 'internal' || l.seg === 'after') return 'wi';
  return l.who === 'client' ? 'wc' : l.who === 'operator' ? 'wo' : 'ws';
}

export function mount(d) {
  if (!audio) {
    audio = document.createElement('audio');
    audio.preload = 'none';
    for (const ev of ['timeupdate', 'play', 'pause', 'ratechange', 'seeked']) audio.addEventListener(ev, update);
    audio.addEventListener('error', () => { if (audio.getAttribute('src')) toast('Запись недоступна. Расшифровка и основания остаются.'); });
  }
  if (!audio.isConnected) S.app.append(audio);
  if (!dialog || dialog.id !== d.id) {
    audio.pause();
    audio.src = api.audioUrl(d.id); // свежая ссылка при входе в карточку: подписанные адреса живут около часа
  }
  dialog = d;
}

export function unmount() {
  if (!audio) return;
  audio.pause();
  audio.remove();
  audio = null;
  dialog = null;
}

// Уход из карточек — запись останавливается.
if (typeof window !== 'undefined') window.addEventListener('hashchange', () => { if (parseHash(location.hash).page !== 'd') unmount(); });

const clamp = t => Math.max(0, Math.min(dialog.dur || t, t));

export function seek(t, play = true) {
  if (!audio || !dialog) return;
  audio.currentTime = clamp(t);
  if (play) audio.play().catch(() => {}); // отказ браузера или сети показывает обработчик error
  update();
}

function update() {
  const d = dialog, ph = document.getElementById('phead');
  if (!d || !audio || !ph) return;
  const t = audio.currentTime;
  ph.style.left = `${(100 * t) / d.dur}%`;
  document.getElementById('ptime').textContent = mmss(t);
  const btn = document.getElementById('pbtn');
  btn.textContent = audio.paused ? '▶' : '❚❚';
  btn.setAttribute('aria-label', audio.paused ? 'Слушать' : 'Пауза');
  document.getElementById('prate').textContent = `${audio.playbackRate}×`;
  const cur = lineAt(d, t);
  document.querySelectorAll('.msg.now').forEach(e => e.classList.remove('now'));
  const el = cur && (cur.who === 'client' || cur.who === 'operator') ? document.getElementById('L' + cur.n) : null;
  if (el) el.classList.add('now');
  document.getElementById('pnow').textContent = el ? `звучит реплика ${cur.n}` : '';
}

// Разметка плеера; булавки — первые основания трёх главных потерь.
export function html(d, losses) {
  const dur = d.dur || 1, t = audio && dialog && dialog.id === d.id ? audio.currentTime : 0;
  const N = 150;
  let bars = '';
  for (let i = 0; i < N; i++) {
    const cls = kindAt(d, ((i + 0.5) / N) * dur);
    const rr = Math.abs(Math.sin(i * 1.93) * Math.cos(i * 0.41)) * 0.8 + ((i * 37) % 11) / 55;
    const h = cls === 'ws' ? 4 : cls === 'wi' ? 6 + Math.round(rr * 18) : 12 + Math.round(rr * 50);
    bars += `<span class="${cls}" style="height:${h}px"></span>`;
  }
  const hatch = folds(d).filter(f => f.t1 - f.t0 > 30).map(f => {
    const l = (100 * f.t0) / dur, w = (100 * (f.t1 - f.t0)) / dur;
    return `<div class="hatch" style="left:${l}%;width:${w}%"></div><div class="hatchlbl" style="left:${l}%;width:${w}%;text-align:center">${esc(f.label)}, не оценивается</div>`;
  }).join('');
  const pins = losses.slice(0, 3).map((r, k) => {
    const ev = (d.res[r.c.id] || {}).ev || [], ln = d.lines.find(l => spoken(l) && l.n === ev[0]);
    return ln ? `<button type="button" class="pin" style="left:${(100 * ln.s) / dur}%" data-act="pin" data-cid="${esc(r.c.id)}" aria-label="Потеря ${k + 1}: ${esc(r.c.name)}, ${mmss(ln.s)}">${k + 1}</button>` : '';
  }).join('');
  const ticks = [];
  for (let m = 0; m * 60 < dur; m++) ticks.push(m * 60);
  const paused = !audio || audio.paused;
  return `<section class="card pad player" aria-label="Запись звонка">
    <div class="row" style="justify-content:space-between">
      <div class="row">
        <button type="button" class="btn pri" id="pbtn" data-act="play" aria-label="${paused ? 'Слушать' : 'Пауза'}" style="width:44px;padding:0;border-radius:50%">${paused ? '▶' : '❚❚'}</button>
        <button type="button" class="btn sm" data-act="skip" data-s="-5">−5 с</button>
        <button type="button" class="btn sm" data-act="skip" data-s="5">+5 с</button>
        <button type="button" class="btn sm" data-act="rate" id="prate">${audio ? audio.playbackRate : 1}×</button>
        <span><b id="ptime">${mmss(t)}</b> / ${mmss(dur)}</span><span class="muted small" id="pnow"></span>
      </div>
      <div class="legend"><span><i style="background:#9AA8A1"></i>Клиент</span><span><i style="background:var(--accent)"></i>Оператор</span><span><i style="background:#D5DBD8"></i>Не оценивается</span><span><i style="background:var(--ev);border-radius:50%"></i>Потеря баллов</span></div>
    </div>
    <div class="wave">${hatch}<div class="bars" data-act="wave" title="Перейти к моменту записи">${bars}</div><div class="playhead" id="phead" style="left:${(100 * t) / dur}%"></div>${pins}</div>
    <div class="ruler" aria-hidden="true">${ticks.map(x => `<span style="left:${(100 * x) / dur}%">${mmss(x)}</span>`).join('')}<span style="left:100%">${mmss(dur)}</span></div>
    <p class="muted xs">Запись монофоническая: участки окрашены по ролям из расшифровки, от начала реплики до начала следующей.</p>
  </section>`;
}

export const actions = {
  play: () => { if (!audio) return; if (audio.paused) audio.play().catch(() => {}); else audio.pause(); },
  skip: t => { if (audio) seek(audio.currentTime + Number(t.dataset.s), !audio.paused); },
  rate: () => { if (audio) audio.playbackRate = audio.playbackRate === 1 ? 1.5 : audio.playbackRate === 1.5 ? 2 : 1; },
  wave: (t, e) => { const b = t.getBoundingClientRect(); seek(((e.clientX - b.left) / b.width) * dialog.dur); },
};
