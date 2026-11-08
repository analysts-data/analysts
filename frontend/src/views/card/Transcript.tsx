// Расшифровка: реплики [data-n] со временем, метки критериев, свёрнутые участки (fold) — соседи строки перед ними.
import { Play } from 'lucide-react';
import { useState } from 'react';
import { ansTxt, mmss } from '../../lib/format.js';
import { ans } from '../../lib/scoring.js';
import { api } from '../../lib/state.js';
import { S } from '../../store';
import { Button, Chip, cn, Tip } from '../../ui';
import { ProsodyBadges } from './Intonation';
import { seek } from './Player';
import { tone } from './util';

export type Marks = { sel: Set<number>; hl: Set<number>; now: number | null; flash: number | null; onFlashEnd: () => void };

/** Ссылка на плеер организаторов, если у реплики нет начала в записи. */
export const OrgPlayer = ({ d }: { d: any }) => (
  <a className="text-[13px]" href={api.playerUrl(d.id)} target="_blank" rel="noopener">
    Открыть в плеере
  </a>
);

export function Transcript({ d, marks, prosody, onCrit, onSeek }: { d: any; marks: Marks; prosody: any; onCrit: (cid: string) => void; onSeek: (l: any) => void }) {
  const [unfolded, setUnfolded] = useState<Set<number>>(new Set());
  if (!d.lines) return <div className="px-4 py-10 text-center text-muted">Расшифровка ещё не загружена. Оценка и обоснования справа.</div>;
  const call = d.ch === 'call';
  const tags: Record<number, { id: string; t: any; tip: string }[]> = {};
  for (const c of S.checklist.criteria) {
    const r = d.res[c.id];
    if (!r || !r.ev) continue;
    const a = ans(d, c.id, S.appeals);
    const t = c.type === 'flag' ? (Object.values(a || {}).some(Boolean) ? 'risk' : 'ok') : tone(c, a);
    const tip = `${c.id} ${c.name}: ${ansTxt(c, a)}`;
    r.ev.forEach((n: number) => (tags[n] = tags[n] || []).push({ id: c.id, t, tip }));
  }
  const out: React.ReactNode[] = [];
  let hidden: any = null;
  for (const l of d.lines) {
    if (l.fold) {
      const shown = unfolded.has(l.from);
      hidden = shown ? null : l;
      out.push(
        <div key={`f${l.from}`} className="fold flex items-center justify-between gap-3 rounded-lg border border-dashed border-line-strong bg-sunken px-3 py-2 text-[13px] text-ink2">
          <span>
            {call ? `${mmss(l.t0)}–${mmss(l.t1)}, ` : ''}
            <b>{l.label}</b>, реплики {l.from}
            {l.to !== l.from ? `–${l.to}` : ''}, не оценивается. <span className="text-muted">Модель видит участок как контекст.</span>
          </span>
          <Button
            size="sm"
            data-act="fold"
            aria-expanded={shown}
            onClick={() =>
              setUnfolded(s => {
                const x = new Set(s);
                x.has(l.from) ? x.delete(l.from) : x.add(l.from);
                return x;
              })
            }
          >
            {shown ? 'Свернуть' : 'Показать'}
          </Button>
        </div>,
      );
      continue;
    }
    if (hidden && l.n >= hidden.from && l.n <= hidden.to) continue;
    const time = call ? mmss(l.t) : l.t;
    const state = cn(marks.sel.has(l.n) && 'sel bg-ev-soft ring-2 ring-ev-line', marks.hl.has(l.n) && 'hl ring-2 ring-info-line', marks.now === l.n && 'now ring-2 ring-ink', marks.flash === l.n && 'flash');
    const tg = (tags[l.n] || []).map(x => (
      <Tip key={x.id} content={x.tip}>
        <button type="button" data-act="crit" data-cid={x.id} onClick={() => onCrit(x.id)} aria-label={`Открыть критерий ${x.tip}`}>
          <Chip tone={x.t}>{x.id}</Chip>
        </button>
      </Tip>
    ));
    const end = marks.flash === l.n ? marks.onFlashEnd : undefined;
    if (l.who === 'system' || l.who === 'bot') {
      out.push(
        <div key={l.n} id={`L${l.n}`} data-n={l.n} onAnimationEnd={end} className={cn('sys flex flex-wrap items-center gap-1.5 rounded-lg px-3 py-1.5 text-center text-xs text-muted', state)}>
          {l.n}, {time}. {l.who === 'bot' ? 'Бот' : 'Система'}: {l.text} {tg}
        </div>,
      );
      continue;
    }
    const op = l.who === 'operator';
    out.push(
      <div
        key={l.n}
        id={`L${l.n}`}
        data-n={l.n}
        onAnimationEnd={end}
        className={cn('msg max-w-[88%] rounded-xl border px-3 py-2', l.who, op ? 'self-end border-transparent bg-accent-soft' : 'self-start border-line bg-surface', state)}
      >
        <header className="mb-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>{l.n}</span>
          <b className="text-ink2">{l.who === 'client' ? 'Клиент' : 'Оператор'}</b>
          <span className="num">{time}</span>
          {call &&
            (l.s == null ? (
              <OrgPlayer d={d} />
            ) : (
              <Tip content={`Слушать с ${mmss(l.s)}`}>
                <button
                  type="button"
                  className="grid h-6 w-6 place-items-center rounded-md text-accent hover:bg-hover"
                  data-act="seek"
                  onClick={() => onSeek(l)}
                  aria-label={`Слушать реплику ${l.n} с ${mmss(l.s)}`}
                >
                  <Play size={13} />
                </button>
              </Tip>
            ))}
          {call && <ProsodyBadges p={prosody} n={l.n} />}
          {tg}
        </header>
        {l.text}
      </div>,
    );
  }
  return <>{out}</>;
}

