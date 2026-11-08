// Оболочка: сайдбар, верхняя панель (крошки, режим, роль, тема), область экрана #view с data-view, toast.
// Id и классы, на которые опираются тесты: .brand, #crumb, #mode, #bQueue, #bAppeals, #view, #toast,
// [data-act="role"][data-role], [data-view] h1.
import { MotionConfig, motion } from 'framer-motion';
import { Bell, ExternalLink, MoreHorizontal, BarChart3, BookOpen, CircleHelp, ListChecks, MessageSquare, Scale, Search, Settings2 } from 'lucide-react';
import { TERMS } from './terms';
import { t } from './i18n';
import { msg } from './lib/i18n.js';
import { LangMenu, ThemeMenu } from './menus';
import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { modeText } from './lib/config.js';
import { api, currentUser, reload, setUser } from './lib/state.js';
import { track } from './lib/telemetry.js';
import { useOps } from './ops';
import { groupOf } from './lib/queue.js';
import { load, rerender, ROLES, save, setRole, useRoute, useS, type Role } from './store';
import { Button, Card, cn, LinkButton, Skeleton, Tip, TipProvider } from './ui';
import { Queue } from './views/Queue';
import { CardView } from './views/Card';
import { Appeals } from './views/Appeals';
import { Checklist } from './views/Checklist';
import { Coaching } from './views/Coaching';
import { ModeDialog } from './views/ModeDialog';
import { Palette } from './palette';
import { available, GROUPS, PAGES, type PageDef } from './pages';
import { PasteHost } from './views/PasteDialog';

// Аналитика тянет ECharts: отдельный кусок сборки, грузится при первом открытии экрана.
const Analytics = lazy(() => import('./views/Analytics').then(m => ({ default: m.Analytics })));

export const NAME = 'CQA';
const NAMES: Record<string, string> = { d: msg('Диалог'), ...Object.fromEntries(PAGES.map(p => [p.page, p.label])) };

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
        on ? 'relative bg-hover font-semibold text-ink before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-brand hover:text-ink' : 'text-ink2 hover:bg-hover hover:text-ink',
      )}
    >
      <span className="flex-none [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>
      {children}
      {badgeId && (
        <span id={badgeId} className={cn('ml-auto min-w-[22px] rounded-full bg-risk px-1.5 text-center text-xs font-semibold text-on-risk', !badge && 'hidden')}>
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
    title: msg('С чего начать'),
    steps: [
      msg('Очередь идёт сверху вниз: грубые ошибки, затем нужна проверка человека, затем диалоги без следующего шага. Начните с верхней группы.'),
      msg('В диалоге у каждого критерия есть балл, обоснование и реплика-основание. «Принять» или «Оставить» решает расхождение моделей, «Исправить оценку» заменяет ответ модели.'),
      msg('Критерии, веса и правила меняются в «Чек-листе». Каждое сохранение создаёт новую версию, новый критерий нужно оценить кнопкой «Оценить набор».'),
    ],
  },
  operator: {
    page: 'coaching',
    title: msg('Как читать оценки'),
    steps: [
      msg('Здесь видно, где диалоги теряют баллы и как сказать лучше, на примерах реплик.'),
      msg('Откройте диалог: у каждого критерия есть балл, объяснение и цитата из разговора.'),
      msg('Не согласны с оценкой: нажмите «Оспорить» в строке критерия и объясните почему. Решение примет проверяющий, исходная оценка сохранится.'),
    ],
  },
  reviewer: {
    page: 'appeals',
    title: msg('Как решать апелляции'),
    steps: [
      msg('Здесь оценки, которые оспорили операторы. Первая ожидающая уже открыта.'),
      msg('Сравните: слева текущая оценка с обоснованием, справа довод оператора, ниже фрагмент диалога с отмеченными репликами.'),
      msg('Выберите «Подтвердить» или «Изменить», напишите причину и сохраните. Итог диалога пересчитается, оператор увидит решение в карточке.'),
    ],
  },
  analytics: {
    page: 'analytics',
    title: msg('Как читать аналитику'),
    steps: [
      msg('Верхний ряд отвечает на четыре вопроса бизнеса: сервис, риски, развитие сотрудников, процессы.'),
      msg('Любое число открывает список диалогов, из него диалог и нужную реплику.'),
      msg('Внизу повторяющиеся причины: укажите, кто исправляет, и скачайте CSV.'),
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
        <h2 className="text-[15px] font-semibold">{t(h.title)}</h2>
        <button
          type="button"
          className="-my-1 rounded-lg px-2.5 py-1 text-[13px] font-semibold text-ink2 hover:bg-hover"
          onClick={() => {
            save(`cqa.hint.${k}`, '1');
            force(x => x + 1);
          }}
        >
          {t('Понятно')}
        </button>
      </div>
      <ol className="mt-2 grid gap-3 text-[13px] text-ink2 md:grid-cols-3">
        {h.steps.map((step, i) => (
          <li key={i} className="flex gap-2.5">
            <span className="mt-px grid h-5 w-5 flex-none place-items-center rounded-full border border-line-strong text-[11px] font-semibold text-muted">{i + 1}</span>
            <span>{t(step)}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

// Ошибка внутри одного экрана не роняет всё приложение: сообщение, «Открыть заново» и переход к диалогам.
class ScreenBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Card className="flex flex-col items-start gap-3 px-5 py-4">
        <h1 className="text-lg font-semibold">{t('Экран не открылся')}</h1>
        <p className="text-[13px] text-muted">{t('Данные не изменены. Попробуйте открыть экран заново; если ошибка повторится, перейдите к списку диалогов.')}</p>
        <p className="font-mono text-xs text-muted">{this.state.error.message}</p>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => this.setState({ error: null })}>
            {t('Открыть заново')}
          </Button>
          <LinkButton href="#/queue">{t('К диалогам')}</LinkButton>
        </div>
      </Card>
    );
  }
}

function View({ page, id }: { page: string; id: string | null }) {
  const S = useS();
  const [busy, setBusy] = useState(false);
  if (S.error)
    return (
      <div className="flex flex-col items-start gap-3">
        <div className="box risk flex flex-col gap-1" role="alert">
          <span className="font-semibold">{t('Не удалось загрузить данные. Сервер ответил ошибкой, ваши данные не потеряны.')}</span>
          <span className="text-xs opacity-80">{S.error}</span>
        </div>
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await reload();
            setBusy(false);
          }}
        >
          {busy ? t('Загружаю…') : t('Повторить')}
        </Button>
      </div>
    );
  if (S.loading)
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <h1 className="sr">{t(NAMES[page])}</h1>
        <p className="sr">{t('Загрузка данных…')}</p>
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
    case 'queue':
      return <Queue />;
    default: {
      const def = PAGES.find(p => p.page === page && p.view && available(p, S.features));
      if (def) {
        const V = def.view!;
        return (
          <Suspense fallback={<Skeleton className="h-72" />}>
            <V id={id} />
          </Suspense>
        );
      }
    }
      return <Queue />;
  }
}

/** Ширина не меньше md: сайдбар и подвал с темой; иначе нижняя панель вкладок. Один экземпляр элементов в DOM. */
function useWide() {
  const q = '(min-width: 768px)';
  const [wide, setWide] = useState(() => globalThis.matchMedia?.(q).matches ?? true);
  useEffect(() => {
    const m = globalThis.matchMedia?.(q);
    const on = () => setWide(m.matches);
    m?.addEventListener('change', on);
    return () => m?.removeEventListener('change', on);
  }, []);
  return wide;
}

// Телефон: четыре главных раздела роли внизу экрана и «Ещё» — палитра со всеми разделами.
const TABS: Record<string, string[]> = { qa: ['queue', 'appeals', 'analytics', 'checklist'], operator: ['coaching', 'queue', 'appeals', 'analytics'], reviewer: ['appeals', 'queue', 'analytics', 'coaching'] };
function TabBar({ role, current, features, queueBadge, appealsBadge, onMore }: { role: string; current: string; features: string[]; queueBadge: number; appealsBadge: number; onMore: () => void }) {
  const items = (TABS[role] ?? TABS.qa).map(k => PAGES.find(p => p.page === k)!).filter(p => available(p, features));
  const cell = 'relative flex min-w-0 flex-col items-center justify-center gap-0.5 px-1 text-[11px] font-medium no-underline [&>svg]:h-5 [&>svg]:w-5';
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 grid h-14 grid-cols-5 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]" aria-label={t('Разделы')}>
      {items.map(p => {
        const on = p.page === current;
        const badge = p.page === 'queue' ? queueBadge : p.page === 'appeals' ? appealsBadge : 0;
        return (
          <a key={p.page} href={`#/${p.page}`} aria-current={on ? 'page' : undefined} className={cn(cell, on ? 'text-accent' : 'text-muted hover:text-ink')}>
            {p.icon}
            <span className="max-w-full truncate">{t(p.label)}</span>
            {badge > 0 && <span className="absolute right-[calc(50%-20px)] top-1.5 min-w-[16px] rounded-full bg-risk px-1 text-center text-[10px] font-semibold leading-4 text-on-risk">{badge}</span>}
          </a>
        );
      })}
      <button type="button" onClick={onMore} className={cn(cell, 'text-muted hover:text-ink')}>
        <MoreHorizontal />
        <span>{t('Ещё')}</span>
      </button>
    </nav>
  );
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

  useOps();
  // Метрики (если сервер их собирает): экран, открытие диалога, действия с data-act — без текста и значений полей.
  useEffect(() => {
    track('page_view');
    if (r.page === 'd') track('dialog_open');
  }, [r.page, r.id]);
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const el = (e.target as Element)?.closest?.('[data-act]') as HTMLElement | null;
      if (el) track('action', { act: el.dataset.act });
    };
    document.addEventListener('click', onClick, true);
    return () => document.removeEventListener('click', onClick, true);
  }, []);

  // Смена экрана: фокус на область содержимого, прокрутка вверх (как в прежнем интерфейсе).
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    window.scrollTo(0, 0);
    main.current?.focus({ preventScroll: true });
  }, [r.page, r.id]);

  const wide = useWide();
  const helpBtn = (
              <Tip content={t('Показать подсказки к этому экрану')}>
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
                  aria-label={t('Подсказки')}
                >
                  <CircleHelp size={17} />
                </button>
              </Tip>
  );
  const navPage = r.page === 'd' ? 'queue' : r.page;
  const queueBadge = S.checklist ? S.dialogs.filter((d: any) => groupOf(d, S.checklist, S.appeals) !== 'other').length : 0;
  const appealsBadge = S.appeals.filter((a: any) => a.status === 'pending').length;
  const warn = S.mode && (S.mode.where === 'external' || (S.mode.where !== 'local' && !S.mode.anonymized));

  return (
    <MotionConfig reducedMotion="user">
      <TipProvider delayDuration={250} skipDelayDuration={100}>
      <button
        type="button"
        onClick={() => main.current?.focus()}
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[80] focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop"
      >
        {t('Перейти к содержимому')}
      </button>
      <div className="grid min-h-screen grid-cols-1 md:grid-cols-[232px_minmax(0,1fr)]" data-role={S.role}>
        {wide ? (
        <aside className="sticky top-0 z-10 flex h-screen flex-col items-stretch gap-0.5 overflow-y-auto border-r border-line bg-surface px-3 py-[18px]">
          <div className="brand hidden items-center gap-2.5 px-2.5 pb-4 pt-0.5 md:flex">
            <i className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-brand not-italic text-white">
              <Logo />
            </i>
            <div>
              <b className="block text-[15px]">{NAME}</b>
              <span className="text-xs text-muted">Freedom Broker</span>
            </div>
          </div>
          {(Object.keys(GROUPS) as PageDef['group'][]).map(g => {
            const items = PAGES.filter(p => p.group === g && available(p, S.features));
            if (!items.length) return null;
            return (
              <div key={g} className="contents">
                <div className="hidden px-3 pb-1 pt-3.5 text-xs font-semibold text-muted md:block">{t(GROUPS[g])}</div>
                <nav className="flex gap-0.5 md:flex-col" aria-label={t(GROUPS[g])}>
                  {items.map(p => (
                    <NavLink
                      key={p.page}
                      page={p.page}
                      current={navPage}
                      icon={p.icon}
                      badge={p.page === 'queue' ? queueBadge : p.page === 'appeals' ? appealsBadge : p.page === 'alerts' ? S.alertsNew : undefined}
                      badgeId={p.page === 'queue' ? 'bQueue' : p.page === 'appeals' ? 'bAppeals' : p.page === 'alerts' ? 'bAlerts' : undefined}
                    >
                      {t(p.label)}
                    </NavLink>
                  ))}
                </nav>
              </div>
            );
          })}
          <div className="mt-auto hidden gap-2 border-t border-line px-3 pt-3 text-xs text-muted md:grid">
            {S.features?.includes('employees') && S.employees?.length > 0 && (
              <label className="grid gap-1">
                <span>{t('Вы вошли как')}</span>
                <select
                  data-act="user"
                  value={currentUser() ?? ''}
                  onChange={e => {
                    const id = e.target.value;
                    setUser(id || null);
                    const emp = S.employees.find((x: any) => x.id === id);
                    if (emp && emp.role in ROLES) setRole(emp.role as Role);
                    reload();
                  }}
                >
                  <option value="">{t('Не выбран')}</option>
                  {S.employees
                    .filter((x: any) => x.active !== false)
                    .map((x: any) => (
                      <option key={x.id} value={x.id}>
                        {x.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <div className="flex items-center gap-2">
              {helpBtn}
              <ThemeMenu />
            </div>
            <span id="clVer">{S.checklist ? t('Чек-лист v{v}', { v: S.checklist.version }) : ''}</span>
            <span>
              {t('Команды:')} <kbd className="rounded border border-line px-1">Ctrl K</kbd>
            </span>
            {S.features?.includes('docs') && (
              <a href={`${api.base.replace(/\/api\/?$/, '')}/docs/`} target="_blank" rel="noopener" className="inline-flex items-center gap-1 font-medium no-underline" onClick={() => track('help_open')}>
                {t('Документация')} <ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
          </div>
        </aside>
        ) : (
          <TabBar role={S.role} current={navPage} features={S.features} queueBadge={queueBadge} appealsBadge={appealsBadge} onMore={() => setPalette(true)} />
        )}
        <div className="min-w-0">
          <header className="no-print z-20 md:sticky md:top-0 flex min-h-[58px] flex-wrap md:flex-nowrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2.5 md:px-7">
            <div className="order-1 min-w-0 flex-1 truncate text-[13px] text-muted" id="crumb">
              {NAME} / <b className="font-semibold text-ink">{t(NAMES[r.page])}</b>
            </div>
            <div className="order-3 flex w-full min-w-0 flex-wrap items-center gap-2.5 md:order-2 md:w-auto md:flex-none md:flex-nowrap">
              <button
                type="button"
                onClick={() => setPalette(true)}
                className="hidden min-h-9 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-[13px] text-muted hover:bg-hover sm:inline-flex"
                aria-label={t('Команды и поиск (Ctrl+K)')}
              >
                <Search size={15} /> <span className="hidden 2xl:inline">{t('Поиск')}</span> <kbd className="rounded border border-line px-1 text-[11px]">Ctrl K</kbd>
              </button>
              {!S.mode ? (
                <span className="h-[22px] w-64 max-w-full rounded-full bg-hover" aria-hidden="true" />
              ) :
                (S.role === 'qa' ? (
                  <Tip content={`${modeText(S.mode, S.llmMode)}. ${t(TERMS.mode)} ${t('Нажмите, чтобы сменить.')}`}>
                  <button
                    type="button"
                    id="mode"
                    data-act="cfg"
                    onClick={() => setModeOpen(true)}
                    aria-label={`${t('Сменить режим оценки.')} ${modeText(S.mode, S.llmMode)}`}
                    className={cn('inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold transition-[filter] hover:brightness-95 md:max-w-[clamp(180px,calc(100vw-1100px),460px)]', warn ? 'bg-ev-soft text-ev' : 'bg-accent-soft text-accent-ink')}
                  >
                    <span className="truncate">{modeText(S.mode, S.llmMode)}</span>
                    <Settings2 size={14} className="flex-none" aria-hidden="true" />
                  </button>
                  </Tip>
                ) : (
                  <Tip content={`${modeText(S.mode, S.llmMode)}. ${t(TERMS.mode)}`}>
                  <span id="mode" tabIndex={0} className={cn('min-w-0 max-w-full truncate rounded-full px-2.5 py-0.5 text-xs font-semibold md:max-w-[clamp(180px,calc(100vw-1100px),460px)]', warn ? 'bg-ev-soft text-ev' : 'bg-accent-soft text-accent-ink')}>
                    {modeText(S.mode, S.llmMode)}
                  </span>
                  </Tip>
                ))}
              <span className="sr-only 2xl:not-sr-only 2xl:whitespace-nowrap 2xl:text-[13px] 2xl:text-muted" id="roleLbl">
                {t('Смотреть как:')}
              </span>
              <div className="inline-flex gap-0.5 rounded-lg bg-sunken p-0.5 ring-1 ring-inset ring-line" role="group" aria-labelledby="roleLbl">
                {(Object.keys(ROLES) as Role[]).map((k, i) => (
                  <Tip key={k} content={k === 'qa' ? t(TERMS.qa) : null}>
                  <button
                    type="button"
                    data-act="role"
                    data-role={k}
                    aria-pressed={S.role === k}
                    onClick={() => setRole(k)}
                    className={cn('min-h-8 rounded-md px-3 text-[13px] font-medium transition-colors', S.role === k ? 'bg-surface text-ink shadow-card ring-1 ring-line' : 'text-muted hover:text-ink')}
                  >
                    {t(ROLES[k])}
                  </button>
                  </Tip>
                ))}
              </div>
            </div>
            {/* иконки: на телефоне в строке с крошками, режим и роли ниже */}
            <div className="order-2 flex flex-none items-center gap-2 md:order-3">
              {S.features?.includes('alerts') && (
                <Tip content={S.alertsNew ? t('Новых алертов: {n}', { n: S.alertsNew }) : t('Алерты')}>
                  <a
                    href="#/alerts"
                    className="relative grid h-9 w-9 place-items-center rounded-lg border border-line-strong bg-surface text-ink2 no-underline hover:bg-hover hover:text-ink"
                    aria-label={S.alertsNew ? t('Алерты, новых: {n}', { n: S.alertsNew }) : t('Алерты')}
                  >
                    <Bell size={17} />
                    {S.alertsNew > 0 && (
                      <span className="absolute -right-1.5 -top-1.5 min-w-[18px] rounded-full bg-risk px-1 text-center text-[11px] font-semibold leading-[18px] text-on-risk">{S.alertsNew}</span>
                    )}
                  </a>
                </Tip>
              )}
              {!wide && helpBtn}
              <LangMenu />
              {!wide && <ThemeMenu />}
            </div>
          </header>
          <main id="view" ref={main} data-view={r.page} tabIndex={-1} className={cn("mx-auto flex w-full max-w-[1480px] flex-col gap-4 px-3.5 pt-4 outline-none md:px-7 md:pt-[22px]", wide ? "pb-14" : "pb-24")}>
            <motion.div key={r.page + (r.id ?? '') + S.lang} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.12 }} className="flex flex-col gap-4">
              {!S.loading && !S.error && hintKey(S.role, r.page) && <RoleHint key={hintKey(S.role, r.page)} k={hintKey(S.role, r.page)} />}
              <ScreenBoundary key={r.page + (r.id ?? '')}>
                <View page={r.page} id={r.id} />
              </ScreenBoundary>
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
