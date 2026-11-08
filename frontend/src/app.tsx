// Оболочка: сайдбар, верхняя панель (крошки, режим, роль, тема), область экрана #view с data-view, toast.
// Id и классы, на которые опираются тесты: .brand, #crumb, #mode, #bQueue, #bAppeals, #view, #toast,
// [data-act="role"][data-role], [data-view] h1.
import { MotionConfig, motion } from 'framer-motion';
import { BarChart3, BookOpen, CircleHelp, ListChecks, MessageSquare, Moon, Scale, Search, Settings2, Sun } from 'lucide-react';
import { TERMS } from './terms';
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { modeText } from './lib/config.js';
import { reload } from './lib/state.js';
import { groupOf } from './lib/queue.js';
import { applyTheme, currentTheme, load, rerender, ROLES, save, setRole, useRoute, useS, type Role } from './store';
import { Card, cn, Skeleton, Tip, TipProvider } from './ui';
import { Queue } from './views/Queue';
import { CardView } from './views/Card';
import { Appeals } from './views/Appeals';
import { Checklist } from './views/Checklist';
import { Coaching } from './views/Coaching';
import { ModeDialog } from './views/ModeDialog';
import { Palette } from './palette';
import { PasteHost } from './views/PasteDialog';

// Аналитика тянет ECharts: отдельный кусок сборки, грузится при первом открытии экрана.
const Analytics = lazy(() => import('./views/Analytics').then(m => ({ default: m.Analytics })));

export const NAME = 'CQA';
const NAMES: Record<string, string> = { queue: 'Диалоги', d: 'Карточка разговора', appeals: 'Апелляции', analytics: 'Аналитика', coaching: 'Обучение', checklist: 'Чек-лист' };

function Logo() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="currentColor" fillRule="evenodd" d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12zM8.3 11.4l2.3 2.3 4.8-4.8-1.3-1.3-3.5 3.5-1-1z" />
    </svg>
  );
}

function NavLink({ page, current, icon, children, badge, badgeId }: { page: string; current: string; icon: React.ReactNode; children: React.ReactNode; badge?: number; badgeId?: string }) {
  const on = page === current;
  return (
    <a
      href={`#/${page}`}
      aria-current={on ? 'page' : undefined}
      className={cn(
        'flex min-h-10 items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 font-medium no-underline transition-colors',
        on ? 'bg-accent-soft font-semibold text-accent-ink hover:text-accent-ink' : 'text-ink2 hover:bg-hover hover:text-ink',
      )}
    >
      <span className="flex-none [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>
      {children}
      {badgeId && (
        <span id={badgeId} className={cn('ml-auto min-w-[22px] rounded-full bg-risk px-1.5 text-center text-xs font-semibold text-white', !badge && 'hidden')}>
          {badge || ''}
        </span>
      )}
    </a>
  );
}

function Toast() {
  const S = useS();
  const [shown, setShown] = useState<{ msg: string; id: number } | null>(null);
  useEffect(() => {
    if (!S.toast) return;
    setShown(S.toast);
    const t = setTimeout(() => setShown(null), 5200);
    return () => clearTimeout(t);
  }, [S.toast?.id]);
  return (
    <div
      id="toast"
      role="status"
      aria-live="polite"
      hidden={!shown}
      className="fixed bottom-5 right-5 z-[60] w-max max-w-[min(420px,calc(100vw-32px))] rounded-xl bg-ink px-4 py-3 text-sm text-bg shadow-pop"
    >
      {shown?.msg}
    </div>
  );
}

// Первый вход: три шага на домашнем экране роли (и на «Аналитике» для руководителя). «Понятно» прячет их,
// кнопка «Подсказки» в шапке показывает снова. Тексты — openspec/reviews/ux-guidelines.md, «Онбординг».
const HINTS: Record<string, { page: string; title: string; steps: string[] }> = {
  qa: {
    page: 'queue',
    title: 'С чего начать',
    steps: [
      'Очередь идёт сверху вниз: грубые ошибки, затем нужна проверка человека, затем диалоги без следующего шага. Начните с верхней группы.',
      'В диалоге у каждого критерия есть балл, обоснование и реплика-основание. «Принять» или «Оставить» решает расхождение моделей, «Исправить оценку» заменяет ответ модели.',
      'Критерии, веса и правила меняются в «Чек-листе». Каждое сохранение создаёт новую версию, новый критерий нужно оценить кнопкой «Оценить набор».',
    ],
  },
  operator: {
    page: 'coaching',
    title: 'Как читать оценки',
    steps: [
      'Здесь видно, где диалоги теряют баллы и как сказать лучше, на примерах реплик.',
      'Откройте диалог: у каждого критерия есть балл, объяснение и цитата из разговора.',
      'Не согласны с оценкой: нажмите «Оспорить» в строке критерия и объясните почему. Решение примет проверяющий, исходная оценка сохранится.',
    ],
  },
  reviewer: {
    page: 'appeals',
    title: 'Как решать апелляции',
    steps: [
      'Здесь оценки, которые оспорили операторы. Первая ожидающая уже открыта.',
      'Сравните: слева текущая оценка с обоснованием, справа довод оператора, ниже фрагмент диалога с отмеченными репликами.',
      'Выберите «Подтвердить» или «Изменить», напишите причину и сохраните. Итог диалога пересчитается, оператор увидит решение в карточке.',
    ],
  },
  analytics: {
    page: 'analytics',
    title: 'Как читать аналитику',
    steps: [
      'Верхний ряд отвечает на четыре вопроса бизнеса: сервис, риски, развитие сотрудников, процессы.',
      'Любое число открывает список диалогов, из него диалог и нужную реплику.',
      'Внизу повторяющиеся причины: укажите, кто исправляет, и скачайте CSV.',
    ],
  },
};
const hintKey = (role: string, page: string) => (page === 'analytics' ? 'analytics' : HINTS[role]?.page === page ? role : null);

function RoleHint({ k }: { k: string }) {
  const [, force] = useState(0);
  if (load(`cqa.hint.${k}`)) return null;
  const h = HINTS[k];
  return (
    <Card className="px-4 py-3.5">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-[15px] font-semibold">{h.title}</h2>
        <button
          type="button"
          className="-my-1 rounded-lg px-2.5 py-1 text-[13px] font-semibold text-ink2 hover:bg-hover"
          onClick={() => {
            save(`cqa.hint.${k}`, '1');
            force(x => x + 1);
          }}
        >
          Понятно
        </button>
      </div>
      <ol className="mt-2 grid gap-3 text-[13px] text-ink2 md:grid-cols-3">
        {h.steps.map((t, i) => (
          <li key={i} className="flex gap-2.5">
            <span className="mt-px grid h-5 w-5 flex-none place-items-center rounded-full border border-line-strong text-[11px] font-semibold text-muted">{i + 1}</span>
            <span>{t}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function View({ page, id }: { page: string; id: string | null }) {
  const S = useS();
  if (S.error)
    return (
      <div className="box risk" role="alert">
        Не удалось загрузить данные: {S.error}
      </div>
    );
  if (S.loading)
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <h1 className="sr">{NAMES[page]}</h1>
        <p className="sr">Загрузка данных…</p>
        <Skeleton className="h-9 w-64" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {[0, 1, 2, 3, 4].map(i => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  switch (page) {
    case 'd':
      return <CardView id={id} />;
    case 'appeals':
      return <Appeals id={id} />;
    case 'checklist':
      return <Checklist />;
    case 'analytics':
      return (
        <Suspense fallback={<Skeleton className="h-72" />}>
          <Analytics />
        </Suspense>
      );
    case 'coaching':
      return <Coaching />;
    default:
      return <Queue />;
  }
}

export function App() {
  const S = useS();
  const r = useRoute();
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const [modeOpen, setModeOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  S.r = r;

  // Живая оценка: пока идёт запуск, состояние подтягивается раз в 3 с — новые ответы появляются без перезагрузки.
  const running = S.run?.status === 'running';
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => reload(), 3000);
    return () => clearInterval(t);
  }, [running]);

  // Смена экрана: фокус на область содержимого, прокрутка вверх (как в прежнем интерфейсе).
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    window.scrollTo(0, 0);
    main.current?.focus({ preventScroll: true });
  }, [r.page, r.id]);

  const navPage = r.page === 'd' ? 'queue' : r.page;
  const theme = currentTheme();
  const queueBadge = S.checklist ? S.dialogs.filter((d: any) => groupOf(d, S.checklist, S.appeals) !== 'other').length : 0;
  const appealsBadge = S.appeals.filter((a: any) => a.status === 'pending').length;
  const warn = S.mode && (S.mode.where === 'external' || (S.mode.where !== 'local' && !S.mode.anonymized));

  return (
    <MotionConfig reducedMotion="user">
      <TipProvider delayDuration={250} skipDelayDuration={100}>
      <div className="grid min-h-screen grid-cols-1 md:grid-cols-[232px_minmax(0,1fr)]" data-role={S.role}>
        <aside className="z-10 flex md:sticky md:top-0 items-center gap-0.5 overflow-x-auto border-b border-line bg-surface px-2 py-1.5 md:h-screen md:flex-col md:items-stretch md:overflow-visible md:border-b-0 md:border-r md:px-3 md:py-[18px]">
          <div className="brand hidden items-center gap-2.5 px-2.5 pb-4 pt-0.5 md:flex">
            <i className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-accent not-italic text-on-accent">
              <Logo />
            </i>
            <div>
              <b className="block text-[15px]">{NAME}</b>
              <span className="text-xs text-muted">Качество диалогов</span>
            </div>
          </div>
          <div className="hidden px-3 pb-1 pt-3.5 text-xs font-semibold text-muted md:block">Работа</div>
          <nav className="flex gap-0.5 md:flex-col" aria-label="Работа">
            <NavLink page="queue" current={navPage} icon={<MessageSquare />} badge={queueBadge} badgeId="bQueue">
              Диалоги
            </NavLink>
            <NavLink page="appeals" current={navPage} icon={<Scale />} badge={appealsBadge} badgeId="bAppeals">
              Апелляции
            </NavLink>
            <NavLink page="coaching" current={navPage} icon={<BookOpen />}>
              Обучение
            </NavLink>
          </nav>
          <div className="hidden px-3 pb-1 pt-3.5 text-xs font-semibold text-muted md:block">Обзор и настройка</div>
          <nav className="flex gap-0.5 md:flex-col" aria-label="Обзор и настройка">
            <NavLink page="analytics" current={navPage} icon={<BarChart3 />}>
              Аналитика
            </NavLink>
            <NavLink page="checklist" current={navPage} icon={<ListChecks />}>
              Чек-лист
            </NavLink>
          </nav>
          <div className="mt-auto hidden gap-0.5 border-t border-line px-3 pt-3 text-xs text-muted md:grid">
            <span id="clVer">{S.checklist ? `Чек-лист v${S.checklist.version}` : ''}</span>
            <span>
              Команды: <kbd className="rounded border border-line px-1">Ctrl K</kbd>
            </span>
          </div>
        </aside>
        <div className="min-w-0">
          <header className="no-print z-20 md:sticky md:top-0 flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-line bg-[var(--top)] px-4 py-2.5 backdrop-blur md:px-7">
            <div className="text-[13px] text-muted" id="crumb">
              {NAME} / <b className="font-semibold text-ink">{NAMES[r.page]}</b>
            </div>
            <div className="flex flex-wrap items-center gap-2.5">
              <button
                type="button"
                onClick={() => setPalette(true)}
                className="hidden min-h-9 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-[13px] text-muted hover:bg-hover sm:inline-flex"
                aria-label="Команды и поиск (Ctrl+K)"
              >
                <Search size={15} /> Поиск <kbd className="rounded border border-line px-1 text-[11px]">Ctrl K</kbd>
              </button>
              {S.mode &&
                (S.role === 'qa' ? (
                  <Tip content={`${TERMS.mode} Нажмите, чтобы сменить.`}>
                  <button
                    type="button"
                    id="mode"
                    data-act="cfg"
                    onClick={() => setModeOpen(true)}
                    aria-label={`Сменить режим оценки. ${modeText(S.mode, S.llmMode)}`}
                    className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold hover:underline', warn ? 'bg-ev-soft text-ev' : 'bg-accent-soft text-accent-ink')}
                  >
                    {modeText(S.mode, S.llmMode)}
                    <Settings2 size={14} aria-hidden="true" />
                  </button>
                  </Tip>
                ) : (
                  <Tip content={TERMS.mode}>
                  <span id="mode" tabIndex={0} className={cn('rounded-full px-2.5 py-0.5 text-xs font-semibold', warn ? 'bg-ev-soft text-ev' : 'bg-accent-soft text-accent-ink')}>
                    {modeText(S.mode, S.llmMode)}
                  </span>
                  </Tip>
                ))}
              <span className="hidden text-[13px] text-muted lg:inline" id="roleLbl">
                Смотреть как:
              </span>
              <div className="inline-flex overflow-hidden rounded-lg border border-line-strong bg-surface" role="group" aria-labelledby="roleLbl">
                {(Object.keys(ROLES) as Role[]).map((k, i) => (
                  <Tip key={k} content={k === 'qa' ? TERMS.qa : null}>
                  <button
                    type="button"
                    data-act="role"
                    data-role={k}
                    aria-pressed={S.role === k}
                    onClick={() => setRole(k)}
                    className={cn('min-h-9 px-3 text-[13px] font-medium', i && 'border-l border-line', S.role === k ? 'bg-ink text-bg' : 'text-ink2 hover:bg-hover')}
                  >
                    {ROLES[k]}
                  </button>
                  </Tip>
                ))}
              </div>
              <Tip content="Показать подсказки к этому экрану">
                <button
                  type="button"
                  onClick={() => {
                    const k = hintKey(S.role, r.page) ?? S.role;
                    try {
                      localStorage.removeItem(`cqa.hint.${k}`);
                    } catch {
                      /* без хранилища подсказка и так видна */
                    }
                    if (!hintKey(S.role, r.page)) location.hash = `#/${HINTS[S.role].page}`;
                    rerender();
                  }}
                  className="grid h-9 w-9 place-items-center rounded-lg border border-line-strong bg-surface text-ink2 hover:bg-hover"
                  aria-label="Подсказки"
                >
                  <CircleHelp size={17} />
                </button>
              </Tip>
              <Tip content={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
              <button
                type="button"
                data-act="theme"
                onClick={() => applyTheme(theme === 'dark' ? 'light' : 'dark', true)}
                className="grid h-9 w-9 place-items-center rounded-lg border border-line-strong bg-surface text-ink2 hover:bg-hover"
                aria-label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
              >
                {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
              </button>
              </Tip>
            </div>
          </header>
          <main id="view" ref={main} data-view={r.page} tabIndex={-1} className="mx-auto flex w-full max-w-[1480px] flex-col gap-4 px-3.5 pb-14 pt-4 outline-none md:px-7 md:pt-[22px]">
            {!S.loading && !S.error && hintKey(S.role, r.page) && <RoleHint key={hintKey(S.role, r.page)} k={hintKey(S.role, r.page)} />}
            <motion.div key={r.page + (r.id ?? '')} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.16 }} className="flex flex-col gap-4">
              <View page={r.page} id={r.id} />
            </motion.div>
          </main>
        </div>
      </div>
      <ModeDialog open={modeOpen} onOpenChange={setModeOpen} />
      <Palette open={palette} onOpenChange={setPalette} />
      <PasteHost />
      <Toast />
      </TipProvider>
    </MotionConfig>
  );
}
