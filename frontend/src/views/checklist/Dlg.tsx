// Нативное модальное окно <dialog id="dlg"> с формой #dlgForm: тесты окна режима и сравнения версий ищут именно их.
// Рисуется, только пока открыто (родитель монтирует его по условию): так в DOM не бывает двух #dlgForm.
// Esc закрывает окно штатно, событие close зовёт onClose.
import { X } from 'lucide-react';
import { useLayoutEffect, useRef, type FormEvent, type ReactNode } from 'react';
import { t } from '../../lib/i18n.js';
import { cn } from '../../ui';

export function Dlg({
  title,
  sub,
  wide,
  onClose,
  onSubmit,
  children,
  footer,
}: {
  title: ReactNode;
  sub?: ReactNode;
  wide?: boolean;
  onClose: () => void;
  onSubmit?: (form: HTMLFormElement) => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    if (!ref.current?.open) ref.current?.showModal();
  }, []);
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault(); // окно закрывает родитель, когда запрос прошёл
    onSubmit?.(e.currentTarget);
  };
  return (
    <dialog
      id="dlg"
      ref={ref}
      aria-labelledby="dlgTitle"
      onClose={onClose}
      className={cn(
        'max-h-[calc(100vh-32px)] rounded-card border border-line bg-surface p-0 text-ink shadow-card backdrop:bg-[rgba(10,16,13,.45)]',
        wide ? 'w-[min(760px,calc(100vw-32px))]' : 'w-[min(560px,calc(100vw-32px))]',
      )}
    >
      {/* шапка и подвал как у Modal из ui.tsx: одно семейство окон */}
      <form id="dlgForm" method="dialog" onSubmit={submit} className="flex flex-col">
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 id="dlgTitle" className="text-base font-semibold">
              {title}
            </h2>
            {sub && <p className="mt-0.5 text-[13px] text-muted">{sub}</p>}
          </div>
          <button
            type="button"
            className="inline-flex size-8 flex-none items-center justify-center rounded-md text-muted hover:bg-hover hover:text-ink"
            aria-label={t('Закрыть')}
            title={t('Закрыть')}
            onClick={() => ref.current?.close()}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="flex flex-col gap-4 px-5 py-4">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </form>
    </dialog>
  );
}
