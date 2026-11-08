// Нативное модальное окно <dialog id="dlg"> с формой #dlgForm: тесты окна режима и сравнения версий ищут именно их.
// Рисуется, только пока открыто (родитель монтирует его по условию): так в DOM не бывает двух #dlgForm.
// Esc закрывает окно штатно, событие close зовёт onClose.
import { useLayoutEffect, useRef, type FormEvent, type ReactNode } from 'react';
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
  footer: ReactNode;
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
      <form id="dlgForm" method="dialog" onSubmit={submit} className="flex flex-col gap-4 px-5 py-4">
        <header>
          <h2 id="dlgTitle" className="text-base font-semibold">
            {title}
          </h2>
          {sub && <p className="mt-0.5 text-[13px] text-muted">{sub}</p>}
        </header>
        {children}
        <footer className="flex flex-wrap justify-end gap-2.5 border-t border-line pt-3">{footer}</footer>
      </form>
    </dialog>
  );
}
