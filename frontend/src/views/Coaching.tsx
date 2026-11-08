// Экран «Обучение»: обратная связь на конкретных репликах, разбор для встречи с оператором.
import { ClipboardCopy, ListChecks, Printer } from 'lucide-react';
import { useRef } from 'react';
import { coachingStats, goodExamples } from '../lib/analytics.js';
import { href } from '../lib/router.js';
import { calc } from '../lib/scoring.js';
import { ansTxt, f2, titleOf } from '../lib/format.js';
import { t } from '../lib/i18n.js';
import { toast } from '../lib/state.js';
import { rerender, useS } from '../store';
import { Button, Card, Chip, cn, Empty, LinkButton, PageHead } from '../ui';

const langName = (l: string) => (({ RU: t('Русский'), KZ: t('Қазақша'), EN: t('English') }) as Record<string, string>)[l];
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
  const totals = S.dialogs.map((d: any) => calc(d, S.checklist, S.appeals).total).filter((x: number | null) => x != null);
  const appeals = S.appeals.filter((a: any) => a.kind === 'appeal');
  const pick = (key: string, on: boolean) => {
    if (on) sheet.add(key);
    else sheet.delete(key);
    rerender();
  };
  const copy = () =>
    navigator.clipboard.writeText(list.current?.innerText ?? '').then(
      () => toast(t('Текст разбора скопирован.')),
      () => toast(t('Браузер не дал доступа к буферу обмена. Выделите текст вручную.')),
    );

  return (
    <>
      <PageHead title={t('Обучение')} sub={t('Обратная связь на конкретных репликах из наших диалогов: где модель снизила балл и как сказать лучше')}>
        {coach && (
          <Button className="no-print" data-act="sheet" onClick={() => document.getElementById('sheet')?.scrollIntoView({ block: 'start' })}>
            <ListChecks size={16} aria-hidden="true" />
            {t('Разбор для встречи: {n}', { n: picked.length })}
          </Button>
        )}
      </PageHead>

      {!coach && (
        <p className="text-ink2">
          {t('Средний итог {avg} из 100 по {n} диалогам.', { avg: totals.length ? f2(totals.reduce((s: number, x: number) => s + x, 0) / totals.length) : '—', n: totals.length })}{' '}
          <a href="#/appeals">
            {t('Апелляции: на рассмотрении {pending}, решено {decided}', {
              pending: appeals.filter((a: any) => a.status === 'pending').length,
              decided: appeals.filter((a: any) => a.status === 'confirmed' || a.status === 'changed').length,
            })}
          </a>
        </p>
      )}

      {groups.length > 0 && (
        <div className="no-print flex flex-col gap-1.5">
          <span className="text-xs text-muted" id="coachLbl">
            {t('Критерий и число моментов, где теряют баллы')}
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
        <section className="flex min-w-0 flex-col gap-3" aria-label={t('Где теряем баллы')}>
          <h2 className="text-base font-semibold">{t('Где теряем баллы')}</h2>
          {sel ? (
            sel.items.map(x => (
              <article key={x.key} className={ARTICLE}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[13px]">
                    <a href={href('d', x.dialogId)}>{titleOf(dlg(x.dialogId))}</a>, {langName(x.lang) || x.lang}
                  </span>
                  <Chip tone="ev">{ansTxt(c, x.answer)}</Chip>
                </div>
                {x.line && <p className="border-l-2 border-ev pl-3 text-[15px]">«{x.line.text}»</p>}
                <p className="text-[13px]">
                  <b>{t('Что не так:')}</b> {x.why}
                </p>
                <p className="text-[13px]">
                  <b>{t('Как сказать лучше:')}</b> «{x.better}»
                </p>
                {coach && (
                  <label className="flex items-center gap-2 text-[13px]">
                    <input type="checkbox" data-act="pick" data-key={x.key} checked={sheet.has(x.key)} onChange={e => pick(x.key, e.target.checked)} />
                    {t('Добавить в разбор')}
                  </label>
                )}
              </article>
            ))
          ) : (
            <Card>
              <Empty action={<LinkButton href="#/queue">{t('Перейти к диалогам')}</LinkButton>}>{t('Подсказок пока нет: они появятся после оценки, где модель снизила балл и предложила формулировку.')}</Empty>
            </Card>
          )}
        </section>
        <section className="flex min-w-0 flex-col gap-3" aria-label={t('Как звучит хороший ответ')}>
          <h2 className="text-base font-semibold">{t('Как звучит хороший ответ')}</h2>
          {good.length ? (
            good.map(g => (
              <article key={`${g.dialogId}/${g.lineNo}`} className={ARTICLE}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[13px]">
                    <a href={href('d', g.dialogId)}>{titleOf(dlg(g.dialogId))}</a>{t(', реплика {n}', { n: g.lineNo })}
                  </span>
                  <Chip tone="ok">{t('полный балл')}</Chip>
                </div>
                <p className="border-l-2 border-ev pl-3 text-[15px]">«{g.text}»</p>
              </article>
            ))
          ) : (
            <Card className="p-4 text-muted">
              {t('В наборе пока нет ответа с полным баллом и цитатой оператора по критерию «{name}». Примеры появятся, когда модель даст полный балл с основанием.', { name: c ? c.name : '' })}
            </Card>
          )}
        </section>
      </div>

      {coach && (
        <Card id="sheet" className="flex scroll-mt-20 flex-col gap-3 p-4" aria-label={t('Разбор для встречи с оператором')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold">{t('Разбор для встречи с оператором')}</h2>
            <div className="no-print flex flex-wrap gap-2">
              <Button data-act="copy" disabled={!picked.length} onClick={copy}>
                <ClipboardCopy size={16} aria-hidden="true" />
                {t('Скопировать текст')}
              </Button>
              <Button data-act="print" disabled={!picked.length} onClick={() => window.print()}>
                <Printer size={16} aria-hidden="true" />
                {t('Печать')}
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
                  {x.why} {t('Лучше: «{text}»', { text: x.better })}
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-muted">{t('Отметьте «Добавить в разбор» у моментов выше, и они соберутся в один лист для встречи.')}</p>
          )}
        </Card>
      )}
    </>
  );
}
