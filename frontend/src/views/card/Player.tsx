// Плеер звонка: настоящий <audio preload="none"> в DOM (шаг защиты читает его currentTime), wavesurfer рисует по нему
// волну с участками реплик (regions), цвет — по говорящему. Запись по /audio уходит редиректом на чужой хост, поэтому
// волна строится из расшифровки (peaks + duration): wavesurfer не скачивает запись, а ошибки звука ловит ws.on('error').
import { Pause, Play } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import WaveSurfer from 'wavesurfer.js';
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';
import { mmss } from '../../lib/format.js';
import { t } from '../../lib/i18n.js';
import { api, toast } from '../../lib/state.js';
import { Button, cn, Tip } from '../../ui';

let audio: HTMLAudioElement | null = null;
let dur = 0;

const spoken = (l: any) => !l.fold && l.s != null;
const folds = (d: any) => d.lines.filter((l: any) => l.fold);

/** Реплика, которая звучит в момент t: последняя начавшаяся, вне свёрнутых участков. */
export function lineAt(d: any, t: number) {
  if (folds(d).some((f: any) => t >= f.t0 && t < f.t1)) return null;
  let cur = null;
  for (const l of d.lines) if (spoken(l) && l.s <= t) cur = l;
  return cur;
}

// wi — не оценивается (fold, seg internal/after), wc — клиент, wo — оператор, ws — тишина
function kindAt(d: any, t: number) {
  if (folds(d).some((f: any) => t >= f.t0 && t < f.t1)) return 'wi';
  const l = lineAt(d, t);
  if (!l) return 'ws';
  if (l.seg === 'internal' || l.seg === 'after') return 'wi';
  return l.who === 'client' ? 'wc' : l.who === 'operator' ? 'wo' : 'ws';
}
const TINT: Record<string, string> = { wc: 'var(--na)', wo: 'var(--accent)', wi: 'var(--line-strong)' };

/** Перемотка к моменту записи; play — сразу слушать. */
export function seek(t: number, play = true) {
  if (!audio) return;
  audio.currentTime = Math.max(0, Math.min(dur || t, t));
  if (play) audio.play().catch(() => {}); // отказ сети покажет обработчик error
}

const css = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

export function Player({ d, losses, theme, onNow, onPin }: { d: any; losses: any[]; theme: string; onNow: (n: number | null) => void; onPin: (cid: string) => void }) {
  const media = useRef<HTMLAudioElement>(null);
  const bars = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const [pos, setT] = useState(0);
  const [paused, setPaused] = useState(true);
  const [rate, setRate] = useState(1);
  const [plain, setPlain] = useState(false); // волна не построилась: остаётся обычный плеер
  const total = d.dur || 1;
  const cur = lineAt(d, pos);
  const nowN = cur && (cur.who === 'client' || cur.who === 'operator') ? cur.n : null;

  useEffect(() => onNow(nowN), [nowN]);

  useEffect(() => {
    const a = media.current!;
    audio = a;
    dur = d.dur || 0;
    const sync = () => {
      setT(a.currentTime);
      setPaused(a.paused);
      setRate(a.playbackRate);
    };
    const evs = ['timeupdate', 'play', 'pause', 'ratechange', 'seeked'];
    evs.forEach(e => a.addEventListener(e, sync));
    let warned = false;
    const fail = () => {
      if (!warned && a.getAttribute('src')) toast(t('Запись недоступна. Расшифровка и основания остаются.'));
      warned = true;
    };
    a.addEventListener('error', fail);
    // Высота столбика — по виду участка, как в прежнем плеере: громкость записи без скачивания неизвестна.
    const N = 300;
    const peaks = Array.from({ length: N }, (_, i) => {
      const k = kindAt(d, ((i + 0.5) / N) * total);
      const rr = Math.abs(Math.sin(i * 1.93) * Math.cos(i * 0.41)) * 0.8 + ((i * 37) % 11) / 55;
      return k === 'ws' ? 0.04 : k === 'wi' ? 0.1 + rr * 0.25 : 0.25 + rr * 0.75;
    });
    let w: WaveSurfer | null = null;
    try {
      w = WaveSurfer.create({
        container: bars.current!,
        media: a,
        peaks: [peaks],
        duration: total,
        height: 64,
        barWidth: 2,
        barGap: 1,
        barRadius: 1,
        waveColor: css('--line-strong'),
        progressColor: css('--accent'),
        cursorColor: css('--ink'),
        cursorWidth: 2,
      });
      const regions = w.registerPlugin(RegionsPlugin.create());
      w.on('error', fail);
      w.on('interaction', () => a.play().catch(() => {}));
      w.once('decode', () => {
        const marks = d.lines.filter((l: any) => spoken(l) || l.fold);
        marks.forEach((l: any, i: number) => {
          const start = l.fold ? l.t0 : l.s;
          const next = marks[i + 1];
          const end = l.fold ? l.t1 : next ? (next.fold ? next.t0 : next.s) : total;
          const kind = l.fold ? 'wi' : kindAt(d, start + 0.01);
          if (kind === 'ws' || end <= start) return;
          const r = regions.addRegion({ start, end, drag: false, resize: false, color: `color-mix(in srgb, ${TINT[kind]} 16%, transparent)` });
          r.element?.classList.add(kind);
          r.element?.setAttribute('title', l.fold ? t('{label}, не оценивается', { label: l.label }) : t('Реплика {n}, {at}', { n: l.n, at: mmss(l.s) }));
        });
      });
      ws.current = w;
    } catch {
      setPlain(true);
    }
    return () => {
      evs.forEach(e => a.removeEventListener(e, sync));
      a.removeEventListener('error', fail);
      a.pause();
      w?.destroy();
      ws.current = null;
      if (audio === a) audio = null;
    };
  }, [d.id]);

  // Тема сменилась: холст волны перекрашивается токенами.
  useEffect(() => {
    ws.current?.setOptions({ waveColor: css('--line-strong'), progressColor: css('--accent'), cursorColor: css('--ink') });
  }, [theme]);

  const toggle = () => {
    const a = media.current!;
    if (a.paused) a.play().catch(() => {});
    else a.pause();
  };
  const skip = (s: number) => seek(media.current!.currentTime + s, !media.current!.paused);
  const nextRate = () => {
    const a = media.current!;
    a.playbackRate = a.playbackRate === 1 ? 1.5 : a.playbackRate === 1.5 ? 2 : 1;
  };
  const hatches = folds(d).filter((f: any) => f.t1 - f.t0 > 30);
  const pins = losses.slice(0, 3).flatMap((r: any, k: number) => {
    const ev = (d.res[r.c.id] || {}).ev || [];
    const ln = d.lines.find((l: any) => spoken(l) && l.n === ev[0]);
    return ln ? [{ k, r, ln }] : [];
  });
  const ticks: number[] = [];
  for (let m = 0; m * 60 < total; m++) ticks.push(m * 60);

  return (
    <section className="player flex flex-col gap-3 rounded-card border border-line bg-surface p-4 shadow-card" aria-label={t('Запись звонка')}>
      <h2 className="sr">{t('Запись звонка')}</h2>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Tip content={paused ? t('Слушать') : t('Пауза')}>
            <Button className="w-10 !px-0" onClick={toggle} aria-label={paused ? t('Слушать') : t('Пауза')}>
              {paused ? <Play size={18} /> : <Pause size={18} />}
            </Button>
          </Tip>
          <Tip content={t('Назад на 5 секунд')}>
            <Button size="sm" onClick={() => skip(-5)}>
              {t('−5 с')}
            </Button>
          </Tip>
          <Tip content={t('Вперёд на 5 секунд')}>
            <Button size="sm" onClick={() => skip(5)}>
              {t('+5 с')}
            </Button>
          </Tip>
          <Tip content={t('Скорость: 1×, 1,5×, 2×')}>
            <Button size="sm" onClick={nextRate} aria-label={t('Скорость {rate}×', { rate })}>
              {rate}×
            </Button>
          </Tip>
          <span className="num">
            <b>{mmss(pos)}</b> / {mmss(total)}
          </span>
          {nowN != null && <span className="text-[13px] text-muted">{t('звучит реплика {n}', { n: nowN })}</span>}
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-muted">
          <Legend tint="var(--na)">{t('Клиент')}</Legend>
          <Legend tint="var(--accent)">{t('Оператор')}</Legend>
          <Legend tint="var(--line-strong)">{t('Не оценивается')}</Legend>
          <Legend tint="var(--ev)">{t('Потеря баллов')}</Legend>
        </div>
      </div>
      <div className="wave relative pt-5">
        {hatches.map((f: any) => (
          <div key={f.from} className="hatch pointer-events-none absolute bottom-0 top-0 z-[1] bg-[repeating-linear-gradient(135deg,transparent_0_6px,var(--line)_6px_8px)]" style={{ left: `${(100 * f.t0) / total}%`, width: `${(100 * (f.t1 - f.t0)) / total}%` }}>
            <span className="block truncate text-center text-[11px] text-muted">{t('{label}, не оценивается', { label: f.label })}</span>
          </div>
        ))}
        <div ref={bars} className="bars relative min-h-16">
          {plain && <PlainBars d={d} total={total} />}
        </div>
        {pins.map(({ k, r, ln }) => (
          <Tip key={k} content={t('Потеря {k}: {name}, {at}', { k: k + 1, name: r.c.name, at: mmss(ln.s) })}>
          <button
            type="button"
            className="pin absolute top-0 z-[2] min-w-[18px] -translate-x-1/2 rounded border border-ev bg-ev-soft px-1 text-[11px] font-semibold leading-4 text-ev hover:bg-ev hover:text-on-accent"
            style={{ left: `${(100 * ln.s) / total}%` }}
            data-act="pin"
            data-cid={r.c.id}
            onClick={() => onPin(r.c.id)}
            aria-label={t('Потеря {k}: {name}, {at}', { k: k + 1, name: r.c.name, at: mmss(ln.s) })}
          >
            {k + 1}
          </button>
          </Tip>
        ))}
      </div>
      <div className="relative h-4 text-[11px] text-muted" aria-hidden="true">
        {ticks.map(x => (
          <span key={x} className="absolute -translate-x-1/2" style={{ left: `${(100 * x) / total}%` }}>
            {mmss(x)}
          </span>
        ))}
      </div>
      <audio ref={media} preload="none" src={api.audioUrl(d.id)} />
      <p className="text-xs text-muted">{t('Нажмите на волну, чтобы перейти к моменту записи. Участки окрашены по ролям из расшифровки.')}</p>
    </section>
  );
}

function Legend({ tint, children }: { tint: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: tint }} />
      {children}
    </span>
  );
}

// Запасная волна без wavesurfer: столбики по ролям, клик перематывает.
function PlainBars({ d, total }: { d: any; total: number }) {
  const N = 150;
  return (
    <div
      className="flex h-16 cursor-pointer items-center gap-px"
      onClick={e => {
        const b = e.currentTarget.getBoundingClientRect();
        seek(((e.clientX - b.left) / b.width) * total);
      }}
    >
      {Array.from({ length: N }, (_, i) => {
        const k = kindAt(d, ((i + 0.5) / N) * total);
        const rr = Math.abs(Math.sin(i * 1.93) * Math.cos(i * 0.41)) * 0.8 + ((i * 37) % 11) / 55;
        const h = k === 'ws' ? 4 : k === 'wi' ? 6 + Math.round(rr * 18) : 12 + Math.round(rr * 50);
        return <span key={i} className={cn(k, 'flex-1 rounded-sm')} style={{ height: h, background: k === 'ws' ? 'var(--line)' : TINT[k] }} />;
      })}
    </div>
  );
}
