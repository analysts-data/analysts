// Режим оценки: тела PUT /api/config и PUT /api/providers/{id} (design/contract.md, «Провайдеры моделей»). Без DOM.
const WHERE = { kz: 'Казахстан', local: 'локально', external: 'внешний провайдер' };
// Плашка режима данных: скрыть нельзя, это ответ про трансграничную передачу на защите.
// llm_mode из GET /api/config: replay — ответы из записей, модель не вызывается.
export const modeText = (m, llmMode) => [`Обработка: ${WHERE[m.where] || m.where}`,
  m.anonymized ? 'транскрипты обезличены' : 'без обезличивания',
  llmMode === 'replay' ? 'Записанные ответы' : `модель ${m.model}`,
  m.verifier ? `второе мнение: ${m.verifier}` : ''].filter(Boolean).join(' · ');

export const configBody = f => ({
  llm_provider: f.llm_provider,
  verifier: f.verifier || null,
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
  if (rawOut(after) && !rawOut(before)) out.push('Транскрипты уйдут во внешний API без обезличивания.');
  if (after.allow_real_data && !before.allow_real_data) out.push('Реальные звонки будут отправляться модели.');
  return out;
}
