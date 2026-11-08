// Режим оценки: тела PUT /api/config и PUT /api/providers/{id} (design/contract.md, «Провайдеры моделей»). Без DOM.
import { t } from './i18n.js';

const whereText = w => ({ kz: t('Казахстан'), local: t('локально'), external: t('внешний провайдер') })[w] || w;
// Плашка режима данных: скрыть нельзя, это ответ про трансграничную передачу на защите.
// llm_mode из GET /api/config: replay — ответы из записей, модель не вызывается.
export const modeText = (m, llmMode) => [t('Обработка: {where}', { where: whereText(m.where) }),
  m.anonymized ? t('транскрипты обезличены') : t('без обезличивания'),
  llmMode === 'replay' ? t('Записанные ответы') : t('модель {model}', { model: m.model }),
  m.verifier ? t('второе мнение: {model}', { model: m.verifier }) : ''].filter(Boolean).join(' · ');

export const configBody = f => ({
  llm_provider: f.llm_provider,
  verifier: f.verifier || null,
  evaluator: f.evaluator === 'jev' ? 'jev' : 'llm',
  anonymize: Boolean(f.anonymize),
  jev_api_key: f.jev_api_key.trim(),
  allow_real_data: Boolean(f.allow_real_data),
});

// Пустой ключ оставляет сохранённый на сервере.
export const providerBody = f => ({
  label: f.label.trim(),
  base_url: f.base_url.trim(),
  model: f.model.trim(),
  profile: f.profile,
  where: f.where,
  key: f.key.trim(),
});

export const whereOf = (cfg, id) => cfg.providers.find(p => p.id === id)?.where;

// Что подтвердить перед сохранением: открытый текст уходит наружу, реальные звонки уходят модели.
export function risks(before, after) {
  const out = [];
  const rawOut = c => c.data_where !== 'local' && !c.anonymize;
  if (rawOut(after) && !rawOut(before)) out.push(t('Транскрипты уйдут во внешний API без обезличивания.'));
  if (after.allow_real_data && !before.allow_real_data) out.push(t('Реальные звонки будут отправляться модели.'));
  return out;
}
