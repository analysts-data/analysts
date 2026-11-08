// Редактор критерия и общих правил. Черновик — S.draft, правка меняет его на каждый ввод и перерисовывает экран.
// Ступени шкалы, подвопросы флага и уточнение для звонка — неуправляемые поля: их текст не равен тому,
// что лежит в черновике (разбор строк, пустое = нет ключа), поэтому поле держит набранное как есть,
// а пересоздаётся, когда черновик заменён целиком (S.cEpoch) или выбран другой критерий.
import { useEffect, useRef } from 'react';
import { syncJev } from '../../lib/checklist_json.js';
import { rerender, S } from '../../store';
import { Term } from '../../terms';
import { Button, Card, Chip, Field } from '../../ui';

const SIGNALS = [
  ['', 'Нет'],
  ['resolution', 'Решение запроса (группа «Без следующего шага»)'],
  ['risk', 'Грубая ошибка'],
];
export const SIGNAL_CHIP: Record<string, string> = { resolution: 'Решение запроса', risk: 'Грубая ошибка' };
const TYPES = [
  ['bool', 'Да / Нет'],
  ['scale', 'Шкала'],
  ['flag', 'Грубая ошибка, без баллов'],
];
const CHANNELS = [
  ['all', 'Все каналы'],
  ['chat', 'Чат'],
  ['call', 'Звонок'],
];

/** Заменить черновик целиком: неуправляемые поля редактора пересоздаются. */
export function setDraft(d: any) {
  S.draft = d;
  S.cEpoch = (S.cEpoch || 0) + 1;
}

const opts = (list: any[][]) =>
  list.map(([v, t]) => (
    <option key={v} value={v}>
      {t}
    </option>
  ));

function setField(c: any, k: string, t: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement) {
  const v = t.value;
  if (k === 'w') c.w = Number(v) || 0;
  else if (k === 'sec') c.sec = Number(v);
  else if (k === 'na') c.na = (t as HTMLInputElement).checked;
  else if (k === 'signal') {
    if (v) c.signal = v;
    else delete c.signal;
  } else if (k === 'call') {
    if (v.trim()) c.call = v;
    else delete c.call; // без ключа черновик совпадает с версией с сервера; сервер читает это как call: null
  } else if (k === 'channel') {
    c.channel = v;
    if (v !== 'all') c.na = true; // контракт: канал без N/A — 422
  } else if (k === 'type') {
    c.type = v;
    if (v === 'scale' && !c.steps) {
      c.steps = [10, 5, 0];
      c.stepText = { 10: 'Полностью', 5: 'Частично', 0: 'Нет' };
    }
    if (v === 'flag' && !c.questions) c.questions = [{ k: 'q1', label: 'Нарушение' }];
  } else if (k === 'steps') {
    const lines = v
      .split('\n')
      .map(s => s.match(/^\s*(\d+)\s*[:—-]?\s*(.*)$/))
      .filter(Boolean) as RegExpMatchArray[];
    if (lines.length) {
      c.steps = lines.map(m => Number(m[1])).sort((a, b) => b - a);
      c.stepText = Object.fromEntries(lines.map(m => [m[1], m[2]]));
    }
  } else if (k === 'questions') {
    c.questions = v
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)
      .map((label, i) => ({ ...(c.questions?.[i] || { k: 'q' + (i + 1) }), label }));
  } else c[k] = v;
  syncJev(c, k === 'channel' ? 'na' : k);
  rerender();
}

export function Editor({ c, readOnly }: { c: any; readOnly: boolean }) {
  const on = (k: string) => (e: { currentTarget: any }) => setField(c, k, e.currentTarget);
  const key = `${c.id}:${S.cEpoch || 0}`;
  const name = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!S.cFocus) return; // только что добавленный критерий: сразу вводить название
    S.cFocus = false;
    name.current?.focus();
  });
  return (
    <Card className="p-5" aria-label="Редактор критерия">
      <fieldset className="flex min-w-0 flex-col gap-4" disabled={readOnly}>
        <legend className="mb-3 flex w-full flex-wrap items-center justify-between gap-2">
          <span className="text-base font-semibold">Критерий {c.id}</span>
          {readOnly && <Chip tone="na">Только просмотр</Chip>}
        </legend>
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label="Название" hint="Видят оператор и проверяющий; модель название не получает.">
            <input id="cf-name" ref={name} className="fld" value={c.name} placeholder="Например: Назвал срок решения" onChange={on('name')} />
          </Field>
          <Field label="Секция">
            <select id="cf-sec" className="fld" value={String(c.sec)} onChange={on('sec')}>
              {opts(S.draft.sections.map((s: string, i: number) => [String(i), s]))}
            </select>
          </Field>
        </div>
        <Field label="Что проверяем" hint="Модель получает этот текст дословно.">
          <textarea id="cf-text" className="fld" value={c.text} placeholder="Да: оператор … Нет: …" onChange={on('text')} />
        </Field>
        <Field label={<Term k="call">Уточнение для звонка</Term>} hint="Необязательно. Модель получает его только на звонках, запрос по чатам не меняется.">
          <textarea key={key} id="cf-call" className="fld min-h-16" defaultValue={c.call || ''} onChange={on('call')} />
        </Field>
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label="Тип ответа" hint={c.type === 'flag' ? 'Не даёт баллов: помечает диалог и ставит его первым в очередь.' : undefined}>
            <select id="cf-type" className="fld" value={c.type} onChange={on('type')}>
              {opts(TYPES)}
            </select>
          </Field>
          {c.type !== 'flag' ? (
            <Field label="Вес" hint="Доля в итоге до перераспределения N/A.">
              <input id="cf-w" className="fld" type="number" min="0" max="100" value={c.w} onChange={on('w')} />
            </Field>
          ) : (
            <span />
          )}
        </div>
        {c.type !== 'flag' && (
          <div className="box na flex flex-col gap-2">
            <label className="flex flex-wrap items-center gap-x-2 font-semibold">
              <input id="cf-na" type="checkbox" checked={!!c.na} onChange={on('na')} />
              Может быть <Term k="na">N/A</Term> (не применимо)
              <span className="basis-full text-xs font-normal text-muted">Если условие выполнено, критерий не оценивается, а его вес делят остальные.</span>
            </label>
            {c.na && (
              <Field label="Когда N/A">
                <input id="cf-nac" className="fld" value={c.naCond || ''} onChange={on('naCond')} />
              </Field>
            )}
          </div>
        )}
        {c.type === 'scale' && (
          <Field label="Ступени шкалы, по строке на ступень: «балл: что значит»" hint="Верхняя ступень даёт полный вес, остальные пропорционально.">
            <textarea key={key} id="cf-steps" className="fld min-h-[130px]" defaultValue={(c.steps || []).map((s: number) => `${s}: ${(c.stepText || {})[s] || ''}`).join('\n')} onChange={on('steps')} />
          </Field>
        )}
        {c.type === 'flag' && (
          <Field label="Подвопросы, по строке на вид нарушения" hint="Каждый подвопрос идёт к модели отдельно. Грубая ошибка отмечается, если найден хотя бы один вид.">
            <textarea key={key} id="cf-q" className="fld" defaultValue={(c.questions || []).map((q: any) => q.label).join('\n')} onChange={on('questions')} />
          </Field>
        )}
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label="Канал" hint="Для одного канала нужен N/A: на другом критерий не оценивается.">
            <select id="cf-ch" className="fld" value={c.channel || 'all'} onChange={on('channel')}>
              {opts(CHANNELS)}
            </select>
          </Field>
          <Field label="Роль в отчётах" hint="Определяет, в какую группу очереди и плитку аналитики попадёт критерий.">
            <select id="cf-sig" className="fld" value={c.signal || ''} onChange={on('signal')}>
              {opts(SIGNALS)}
            </select>
          </Field>
        </div>
        {!readOnly && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line2 pt-3.5">
            <span className="max-w-xl text-[13px] text-muted">
              Смена веса пересчитывает итоги сразу. Смена текста, типа, шкалы или N/A требует новой оценки этого критерия, смена уточнения для звонка требует новой оценки только звонков.
            </span>
            <Button variant="danger" data-act="cdel" onClick={() => del(c.id)}>
              Удалить критерий
            </Button>
          </div>
        )}
      </fieldset>
    </Card>
  );
}

function del(id: string) {
  S.draft.criteria = S.draft.criteria.filter((x: any) => x.id !== id);
  S.cSel = null;
  rerender();
}

export function RulesEditor({ readOnly }: { readOnly: boolean }) {
  return (
    <Card className="p-5" aria-label="Общие правила">
      <fieldset disabled={readOnly}>
        <Field
          label="Общие правила"
          hint="Модель получает правила вместе с каждым критерием. Смена правил меняет смысл всех критериев: после сохранения весь чек-лист ждёт новой оценки."
        >
          <textarea
            id="cl-rules"
            className="fld min-h-[150px]"
            value={S.draft.rules ?? ''}
            onChange={e => {
              S.draft.rules = e.currentTarget.value;
              rerender();
            }}
          />
        </Field>
      </fieldset>
    </Card>
  );
}
