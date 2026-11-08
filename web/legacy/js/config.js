// Режим оценки: три пресета интерфейса и тело PUT /api/config (design/contract.md). Без DOM.
export const PRESETS = {
  local: 'Локальная модель',
  anon: 'Внешний API, обезличенные данные',
  raw: 'Внешний API без обезличивания',
};

const WHERE = { kz: 'Казахстан', local: 'локально', external: 'внешний провайдер' };
// Плашка режима данных: скрыть нельзя, это ответ про трансграничную передачу на защите.
// llm_mode из GET /api/config: replay — ответы из записей, модель не вызывается.
export const modeText = (m, llmMode) => [`Обработка: ${WHERE[m.where] || m.where}`,
  m.anonymized ? 'транскрипты обезличены' : 'без обезличивания',
  llmMode === 'replay' ? 'Записанные ответы' : `модель ${m.model}`,
  m.verifier ? `второе мнение: ${m.verifier}` : ''].filter(Boolean).join(' · ');

export const presetOf = cfg => (cfg.data_where === 'local' ? 'local' : cfg.anonymize ? 'anon' : 'raw');

// Локальная модель не выводит данные наружу, поэтому обезличивание ей не нужно.
export const configBody = (preset, where, f) => ({
  llm_base_url: f.llm_base_url.trim(),
  llm_model: f.llm_model.trim(),
  llm_profile: f.llm_profile,
  llm_api_key: f.llm_api_key.trim(),
  data_where: preset === 'local' ? 'local' : where,
  anonymize: preset === 'anon',
  verifier: f.jev ? 'jev' : null,
  evaluator: f.evaluator === 'jev' ? 'jev' : 'llm',
  jev_api_key: f.jev_api_key.trim(),
  allow_real_data: Boolean(f.allow_real_data),
});

// Что подтвердить перед сохранением: открытый текст уходит наружу, реальные звонки уходят модели.
export function risks(before, after) {
  const out = [];
  const rawOut = c => c.data_where !== 'local' && !c.anonymize;
  if (rawOut(after) && !rawOut(before)) out.push('Транскрипты уйдут во внешний API без обезличивания.');
  if (after.allow_real_data && !before.allow_real_data) out.push('Реальные звонки будут отправляться модели.');
  return out;
}
