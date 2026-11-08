import './index.css';
import { createRoot } from 'react-dom/client';
import { App } from './app';
import { resolveBase } from './lib/api.js';
import { api, init, reload, resumeRun } from './lib/state.js';
import { homeOf, load, S, rerender, systemTheme } from './store';

const root = document.querySelector('cqa-app') as HTMLElement;
init(resolveBase(location.search, root.dataset.api));

// Тема до первой отрисовки: выбор пользователя, иначе системная.
const theme = load('cqa.theme');
document.documentElement.dataset.theme = theme === 'dark' || theme === 'light' ? theme : systemTheme();

if (!location.hash || location.hash === '#/' || location.hash === '#') history.replaceState(null, '', homeOf(S.role));

createRoot(root).render(<App />);
reload();
resumeRun(); // перезагрузка во время оценки: продолжаем опрос запомненного запуска
// llm_mode задаёт .env и из интерфейса не меняется: хватит одного запроса
api.getConfig().then(
  (c: any) => {
    S.llmMode = c.llm_mode;
    rerender();
  },
  () => {},
);
