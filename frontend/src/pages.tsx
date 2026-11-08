// Реестр экранов: пункт меню, группа, функция сервера, без которой экран скрыт, и сам экран.
// Новые разделы грузятся отдельными кусками сборки и появляются в меню, только когда сервер их объявил
// (GET /api/config → features): на сервере без функции интерфейс не зовёт её эндпоинты.
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  Bot,
  Database,
  FileText,
  History,
  Layers,
  ListChecks,
  MessageSquare,
  Route,
  Scale,
  Users,
} from 'lucide-react';
import { lazy, type ComponentType, type ReactNode } from 'react';

const lazyView = (load: () => Promise<Record<string, ComponentType<any>>>, name: string) => lazy(() => load().then(m => ({ default: m[name] })));

export type PageDef = {
  page: string;
  label: string; // русский ключ перевода
  group: 'work' | 'overview' | 'data' | 'settings';
  icon: ReactNode;
  feature?: string;
  view?: ComponentType<{ id: string | null }>;
};

export const GROUPS: Record<PageDef['group'], string> = { work: 'Работа', overview: 'Обзор', data: 'Данные', settings: 'Настройка' };

// queue, d, appeals, checklist, analytics, coaching рисует app.tsx (они под тестами защиты и грузятся сразу)
export const PAGES: PageDef[] = [
  { page: 'queue', label: 'Диалоги', group: 'work', icon: <MessageSquare /> },
  { page: 'appeals', label: 'Апелляции', group: 'work', icon: <Scale /> },
  { page: 'alerts', label: 'Алерты', group: 'work', icon: <Bell />, feature: 'alerts', view: lazyView(() => import('./views/Alerts'), 'Alerts') },
  { page: 'coaching', label: 'Обучение', group: 'work', icon: <BookOpen /> },
  { page: 'analytics', label: 'Аналитика', group: 'overview', icon: <BarChart3 /> },
  { page: 'people', label: 'Сотрудники', group: 'overview', icon: <Users />, feature: 'employees', view: lazyView(() => import('./views/People'), 'People') },
  { page: 'reports', label: 'Отчёты', group: 'overview', icon: <FileText />, feature: 'reports', view: lazyView(() => import('./views/Reports'), 'Reports') },
  { page: 'sources', label: 'Источники данных', group: 'data', icon: <Database />, feature: 'sources', view: lazyView(() => import('./views/Sources'), 'Sources') },
  { page: 'batches', label: 'Пакеты', group: 'data', icon: <Layers />, feature: 'batches', view: lazyView(() => import('./views/Batches'), 'Batches') },
  { page: 'automation', label: 'Автоматизация', group: 'data', icon: <Bot />, feature: 'automation', view: lazyView(() => import('./views/Automation'), 'Automation') },
  { page: 'checklist', label: 'Чек-лист', group: 'settings', icon: <ListChecks /> },
  { page: 'routing', label: 'Правила обработки', group: 'settings', icon: <Route />, feature: 'routing', view: lazyView(() => import('./views/Routing'), 'Routing') },
  { page: 'audit', label: 'Журнал действий', group: 'settings', icon: <History />, feature: 'audit', view: lazyView(() => import('./views/Audit'), 'Audit') },
  { page: 'usage', label: 'Использование', group: 'settings', icon: <Activity />, feature: 'usage', view: lazyView(() => import('./views/Usage'), 'Usage') },
];

/** Экран доступен: базовый или его функцию объявил сервер. */
export const available = (p: PageDef, features: string[] | undefined) => !p.feature || !!features?.includes(p.feature);
