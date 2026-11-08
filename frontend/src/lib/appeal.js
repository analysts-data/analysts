// Чистые функции окна апелляции (перенесены из web/js/appeal_form.js).

// Допустимые ответы критерия: ступени шкалы или да/нет, N/A — только где разрешён.
export const allowed = c => [...(c.type === 'scale' ? c.steps : ['yes', 'no']), ...(c.na ? ['na'] : [])];

// Подпись текущей роли в полях by и reviewer.
const SIGN = { qa: 'Специалист КК', operator: 'Оператор', reviewer: 'Проверяющий' };
export const signOf = role => SIGN[role];

// Значение из атрибута или поля формы: ступень шкалы — число, остальное — строка.
export const answerOf = v => (/^\d+$/.test(v) ? Number(v) : v);
