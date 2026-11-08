import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Сборка в ../web: относительные пути (Dynamics 365), имена без хешей, расчёт итога дословно в js/scoring.js
// (сценарий защиты импортирует /js/scoring.js в странице).
export default defineConfig({
  base: './',
  plugins: [
    react(),
    {
      name: 'scoring-js',
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'js/scoring.js', source: readFileSync(new URL('./src/lib/scoring.js', import.meta.url), 'utf8') });
      },
    },
  ],
  build: {
    outDir: '../web',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      output: { entryFileNames: 'assets/[name].js', chunkFileNames: 'assets/[name].js', assetFileNames: 'assets/[name][extname]' },
    },
  },
  server: { proxy: { '/api': process.env.CQA_API ?? 'http://127.0.0.1:8000' } },
});
