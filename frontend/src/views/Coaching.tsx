// Экран «Обучение»: обратная связь на конкретных репликах, разбор для встречи с оператором.
import { ClipboardCopy, ListChecks, Printer } from 'lucide-react';
import { useRef } from 'react';
import { coachingStats, goodExamples } from '../lib/analytics.js';
import { href } from '../lib/router.js';
import { calc } from '../lib/scoring.js';
import { ansTxt, f2, titleOf } from '../lib/format.js';
import { toast } from '../lib/state.js';
import { rerender, useS } from '../store';
import { Button, Card, Chip, cn, Empty, LinkButton, PageHead } from '../ui';

const LANG: Record<string, string> = { RU: 'Русский', KZ: 'Қазақша', EN: 'English' };
// Выбор критерия и отмеченные моменты живут между переходами (как в прежнем интерфейсе): из карточки можно вернуться к разбору.
let selected: string | null = null;
const sheet = new Set<string>();

const ARTICLE = 'flex flex-col gap-2.5 rounded-card border border-line bg-surface p-4 shadow-card';

export function Coaching() {
  const S = useS();
  const list = useRef<HTMLOListElement>(null);
  const groups = coachingStats(S).groups;
  if (!groups.some(g => g.cid === selected)) selected = groups[0]?.cid ?? null;
  const crit = (id: string) => S.checklist.criteria.find((c: any) => c.id === id);
  const dlg = (id: string) => S.dialogs.find((d: any) => d.id === id);
  const sel = groups.find(g => g.cid === selected);
  const c = selected && crit(selected);
  const picked = groups.flatMap(g => g.items.map(x => ({ ...x, c: crit(g.cid) }))).filter(x => sheet.has(x.key));
  const good = c ? goodExamples(S, c.id) : [];
  // Разбор для встречи — инструмент специалиста и руководителя, оператору не показываем.
  const coach = S.role !== 'operator';
  const totals = S.dialogs.map((d: any) => calc(d, S.checklist, S.appeals).total).filter((t: number | null) => t != null);
  const appeals = S.appeals.filter((a: any) => a.kind === 'appeal');
  const pick = (key: string, on: boolean) => {
    if (on) sheet.add(key);
    else sheet.delete(key);
    rerender();
  };
  const copy = () =>
    navigator.clipboard.writeText(list.current?.innerText ?? '').then(
      () => toast('Текст разбора скопирован.'),
      () => toast('Браузер не дал доступа к буферу обмена. Выделите текст вручную.'),
    );

  return (
    <>
      <PageHead title="Обучение" sub="Обратная связь на конкретных репликах из наших диалогов: где модель снизила балл и как сказать лучше">
        {coach && (
        <Button className="no-print" data-act="sheet" onClick={() => document.getElementById('sheet')?.scrollIntoView({ block: 'start' })} title="Перейти к листу для встречи с оператором">
          <ListChecks size={16} aria-hidden="true" />
          Разбор для встречи: {picked.length}
        </Button>
        )}
      </PageHead>

      {!coach && (
        <p className="text-ink2">
          Средний итог {totals.length ? f2(totals.reduce((s: number, t: number) => s + t, 0) / totals.length) : '—'} из 100 по {totals.length} диалогам.{' '}
          <a href="#/appeals">
            Апелляции: на рассмотрении {appeals.filter((a: any) => a.status === 'pending').length}, решено {appeals.filter((a: any) => a.status === 'confirmed' || a.status === 'changed').length}
          </a>
        </p>
      )}

      {groups.length > 0 && (
        <div className="no-print flex flex-col gap-1.5">
          <span className="text-xs text-muted" id="coachLbl">
            Критерий и число моментов, где теряют баллы
          </span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="coachLbl">
            {groups.map(g => (
              <button
                key={g.cid}
                type="button"
                data-act="coach"
                data-cid={g.cid}
                aria-pressed={g.cid === selected}
                onClick={() => {
                  selected = g.cid;
                  rerender();
                }}
                className={cn('min-h-9 rounded-lg border px-3 text-[13px] font-medium', g.cid === selected ? 'border-ink bg-ink text-bg' : 'border-line-strong bg-surface text-ink2 hover:bg-hover')}
              >
                {g.cid} {crit(g.cid).name}: {g.items.length}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="no-print grid gap-4 lg:grid-cols-2">
        <section className="flex min-w-0 flex-col gap-3" aria-label="Где теряем баллы">
          <h2 className="text-base font-semibold">Где теряем баллы</h2>
          {sel ? (
            sel.items.map(x => (
              <article key={x.key} className={ARTICLE}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[13px]">
                    <a href={href('d', x.dialogId)}>{titleOf(dlg(x.dialogId))}</a>, {LANG[x.lang] || x.lang}
                  </span>
                  <Chip tone={c.type === 'bool' ? 'risk' : 'ev'} title="Ответ модели с учётом решений специалистов">
                    {ansTxt(c, x.answer)}
                  </Chip>
                </div>
                {x.line && <p className="border-l-2 border-ev pl-3 text-[15px]">«{x.line.text}»</p>}
                <p className="text-[13px]">
                  <b>Что не так:</b> {x.why}
                </p>
                <p className="text-[13px]">
                  <b>Как сказать лучше:</b> «{x.better}»
                </p>
                {coach && (
                  <label className="flex items-center gap-2 text-[13px]">
                    <input type="checkbox" data-act="pick" data-key={x.key} checked={sheet.has(x.key)} onChange={e => pick(x.key, e.target.checked)} />
                    Добавить в разбор
                  </label>
                )}
              </article>
            ))
          ) : (
            <Card>
              <Empty action={<LinkButton href="#/queue">Перейти к диалогам</LinkButton>}>Подсказок пока нет: они появятся после оценки, где модель снизила балл и предложила формулировку.</Empty>
            </Card>
          )}
        </section>
        <section className="flex min-w-0 flex-col gap-3" aria-label="Как звучит хороший ответ">
          <h2 className="text-base font-semibold">Как звучит хороший ответ</h2>
          {good.length ? (
            good.map(g => (
              <article key={`${g.dialogId}/${g.lineNo}`} className={ARTICLE}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[13px]">
                    <a href={href('d', g.dialogId)}>{titleOf(dlg(g.dialogId))}</a>, реплика {g.lineNo}
                  </span>
                  <Chip tone="ok">полный балл</Chip>
                </div>
                <p className="border-l-2 border-ev pl-3 text-[15px]">«{g.text}»</p>
              </article>
            ))
          ) : (
            <Card className="p-4 text-muted">
              В наборе пока нет ответа с полным баллом и цитатой оператора по критерию «{c ? c.name : ''}». Примеры появятся, когда модель даст полный балл с основанием.
            </Card>
          )}
        </section>
      </div>

      {coach && (
      <Card id="sheet" className="flex scroll-mt-20 flex-col gap-3 p-4" aria-label="Разбор для встречи с оператором">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Разбор для встречи с оператором</h2>
          <div className="no-print flex flex-wrap gap-2">
            <Button data-act="copy" disabled={!picked.length} onClick={copy}>
              <ClipboardCopy size={16} aria-hidden="true" />
              Скопировать текст
            </Button>
            <Button data-act="print" disabled={!picked.length} onClick={() => window.print()}>
              <Printer size={16} aria-hidden="true" />
              Печать
            </Button>
          </div>
        </div>
        {picked.length ? (
          <ol ref={list} className="m-0 flex list-decimal flex-col gap-2 pl-5">
            {picked.map(x => (
              <li key={x.key}>
                <b>
                  {titleOf(dlg(x.dialogId))}, {x.c.name}.
                </b>{' '}
                {x.why} Лучше: «{x.better}»
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted">Отметьте «Добавить в разбор» у моментов выше, и они соберутся в один лист для встречи.</p>
        )}
      </Card>
      )}
    </>
  );
}
