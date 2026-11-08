import { t } from '../lib/i18n.js';
import { PageHead } from '../ui';

export function Batches(_: { id: string | null }) {
  return <PageHead title={t('Пакеты')} />;
}
