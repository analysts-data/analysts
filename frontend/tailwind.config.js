// Цвета — токены :root прототипа (design/cqa-v3), тёмная тема переопределяет те же переменные.
const v = n => `var(--${n})`;
export default {
  content: ['./index.html', './src/**/*.{ts,tsx,js}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: Object.fromEntries(
        ['bg', 'surface', 'hover', 'line', 'line2', 'line-strong', 'ink', 'ink2', 'muted', 'accent', 'accent-ink', 'accent-soft',
          'ev', 'ev-line', 'ev-soft', 'risk', 'risk-soft', 'info', 'info-line', 'info-soft', 'na', 'na-soft', 'on-accent', 'sunken', 'brand', 'on-risk', 'field'].map(n => [n, v(n)]),
      ),
      fontFamily: { sans: 'var(--font)' },
      borderRadius: { card: 'var(--r)' },
      boxShadow: { card: 'var(--shadow)', pop: 'var(--shadow-pop)' },
    },
  },
};
