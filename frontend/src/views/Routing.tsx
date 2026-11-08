import { t } from '../lib/i18n.js';
import { PageHead } from '../ui';

export function Routing(_: { id: string | null }) {
  return <PageHead title={t('Правила обработки')} />;
}
