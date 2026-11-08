import { PageHead } from '../ui';

export function CardView({ id }: { id: string | null }) {
  return <PageHead title={id ?? 'Карточка'} />;
}
