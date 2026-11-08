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
  ShieldCheck,
  Tags,
  Users,
} from 'lucide-react';
import { lazy, type ComponentType, type ReactNode } from 'react';
import { msg } from './lib/i18n.js';

const lazyView = (load: () => Promise<Record<string, ComponentType<any>>>, name: string) => lazy(() => load().then(m => ({ default: m[name] })));

export type PageDef = {
  page: string;
  label: string; // русский ключ перевода
  group: 'work' | 'overview' | 'data' | 'settings';
  icon: ReactNode;
  feature?: string;
  view?: ComponentType<{ id: string | null }>;
};

export const GROUPS: Record<PageDef['group'], string> = { work: msg('Работа'), overview: msg('Обзор'), data: msg('Данные'), settings: msg('Настройка') };

// queue, d, appeals, checklist, analytics, coaching рисует app.tsx (они под тестами защиты и грузятся сразу)
export const PAGES: PageDef[] = [
  { page: 'queue', label: msg('Диалоги'), group: 'work', icon: <MessageSquare /> },
  { page: 'appeals', label: msg('Апелляции'), group: 'work', icon: <Scale /> },
  { page: 'alerts', label: msg('Алерты'), group: 'work', icon: <Bell />, feature: 'alerts', view: lazyView(() => import('./views/Alerts'), 'Alerts') },
  { page: 'customer-cases', label: msg('Клиентские случаи'), group: 'work', icon: <Users />, view: lazyView(() => import('./views/CustomerCases'), 'CustomerCases') },
  { page: 'coaching', label: msg('Обучение'), group: 'work', icon: <BookOpen /> },
  { page: 'analytics', label: msg('Аналитика'), group: 'overview', icon: <BarChart3 /> },
  { page: 'people', label: msg('Сотрудники'), group: 'overview', icon: <Users />, feature: 'employees', view: lazyView(() => import('./views/People'), 'People') },
  { page: 'reports', label: msg('Отчёты'), group: 'overview', icon: <FileText />, feature: 'reports', view: lazyView(() => import('./views/Reports'), 'Reports') },
  { page: 'sources', label: msg('Источники данных'), group: 'data', icon: <Database />, feature: 'sources', view: lazyView(() => import('./views/Sources'), 'Sources') },
  { page: 'batches', label: msg('Пакеты'), group: 'data', icon: <Layers />, feature: 'batches', view: lazyView(() => import('./views/Batches'), 'Batches') },
  { page: 'automation', label: msg('Автоматизация'), group: 'data', icon: <Bot />, feature: 'automation', view: lazyView(() => import('./views/Automation'), 'Automation') },
  { page: 'checklist', label: msg('Чек-лист'), group: 'settings', icon: <ListChecks /> },
  { page: 'routing', label: msg('Правила обработки'), group: 'settings', icon: <Route />, feature: 'routing', view: lazyView(() => import('./views/Routing'), 'Routing') },
  { page: 'products', label: msg('Темы обращений'), group: 'settings', icon: <Tags />, feature: 'products', view: lazyView(() => import('./views/Products'), 'Products') },
  { page: 'sufficiency', label: msg('Достаточность данных'), group: 'settings', icon: <ShieldCheck />, feature: 'sufficiency', view: lazyView(() => import('./views/Sufficiency'), 'Sufficiency') },
  { page: 'audit', label: msg('Журнал действий'), group: 'settings', icon: <History />, feature: 'audit', view: lazyView(() => import('./views/Audit'), 'Audit') },
  { page: 'usage', label: msg('Использование'), group: 'settings', icon: <Activity />, feature: 'usage', view: lazyView(() => import('./views/Usage'), 'Usage') },
];

/** Экран доступен: базовый или его функцию объявил сервер. */
export const available = (p: PageDef, features: string[] | undefined) => !p.feature || !!features?.includes(p.feature);
