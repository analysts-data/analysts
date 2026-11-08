// «Выгрузить оценки (CSV)»: GET /api/scores/export (design/contract.md) с фильтрами языка и канала очереди.
// Файл через fetch, а не ссылкой: заголовок X-CQA-User уходит, а кнопка показывает «Готовится файл…».
import { Download } from 'lucide-react';
import { useState } from 'react';
import { t } from '../../lib/i18n.js';
import { api, toast, userHeader } from '../../lib/state.js';
import { Button } from '../../ui';

export function ExportButton({ lang, ch }: { lang?: string; ch?: string }) {
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    try {
      const q = new URLSearchParams({
        format: 'csv',
        shape: 'wide',
        ...(lang && { lang }),
        ...(ch && { ch }),
      });
      const res = await fetch(`${api.base}/scores/export?${q}`, {
        headers: userHeader(),
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      const name = /filename="?([^";]+)"?/.exec(res.headers.get('content-disposition') || '')?.[1] || 'cqa-scores.csv';
      const a = document.createElement('a');
      a.href = URL.createObjectURL(await res.blob());
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e: any) {
      toast(t('Оценки не выгружены: {e}', { e: e.message }));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button data-act="export" disabled={busy} onClick={download}>
      <Download size={16} aria-hidden="true" /> {busy ? t('Готовится файл…') : t('Выгрузить оценки (CSV)')}
    </Button>
  );
}
