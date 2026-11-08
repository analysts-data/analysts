// Общие элементы интерфейса в духе shadcn/ui: Tailwind на токенах прототипа, Radix Dialog для окон.
import * as D from '@radix-ui/react-dialog';
import * as T from '@radix-ui/react-tooltip';

export const TipProvider = T.Provider;
import { X } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { t } from './lib/i18n.js';

export const cn = (...a: unknown[]) => a.filter(Boolean).join(' ');

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'primary' | 'ghost' | 'danger'; size?: 'md' | 'sm' };
const VARIANT = {
  default: 'border border-line-strong bg-surface text-ink hover:bg-hover',
  primary: 'border border-accent bg-accent text-on-accent hover:bg-accent-ink hover:border-accent-ink',
  ghost: 'border border-transparent bg-transparent text-ink2 hover:bg-hover',
  danger: 'border border-risk bg-surface text-risk hover:bg-risk-soft',
};
/** Кнопка; по умолчанию type="button". */
export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button({ variant = 'default', size = 'md', className, type = 'button', ...p }, ref) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        size === 'sm' ? 'min-h-8 px-2.5 text-[13px]' : 'min-h-10 px-3.5',
        VARIANT[variant],
        className,
      )}
      {...p}
    />
  );
});

/** Ссылка в виде кнопки. */
export function LinkButton({ variant = 'default', size = 'md', className, ...p }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: keyof typeof VARIANT; size?: 'md' | 'sm' }) {
  return (
    <a
      className={cn(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-semibold no-underline transition-colors',
        size === 'sm' ? 'min-h-8 px-2.5 text-[13px]' : 'min-h-10 px-3.5',
        VARIANT[variant],
        variant === 'primary' ? 'hover:text-on-accent' : 'hover:text-ink',
        className,
      )}
      {...p}
    />
  );
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLElement> & { children?: ReactNode }) {
  return (
    <section className={cn('rounded-card border border-line bg-surface shadow-card', className)} {...p}>
      {children}
    </section>
  );
}

const TONE = {
  risk: 'bg-risk-soft text-risk',
  ev: 'bg-ev-soft text-ev',
  info: 'bg-info-soft text-info',
  ok: 'bg-accent-soft text-accent-ink',
  na: 'bg-na-soft text-na',
};
export type Tone = keyof typeof TONE;
export function Chip({ tone = 'na', className, children, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 text-xs font-semibold leading-5', TONE[tone], className)} {...p}>
      {children}
    </span>
  );
}

/** Подпись поля: <label> оборачивает поле, поэтому get_by_label находит его. */
export function Field({ label, hint, className, children }: { label: ReactNode; hint?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <label className={cn('flex flex-col gap-1.5', className)}>
      <span className="text-[13px] font-semibold text-ink2">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

/** Заголовок экрана: h1 обязателен (тесты ищут [data-view] h1). */
export function PageHead({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-muted">{sub}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2.5">{children}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('rounded-md bg-hover', className)} aria-hidden="true" />;
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center text-muted">
      <div>{children}</div>
      {action}
    </div>
  );
}

/** Модальное окно (Radix Dialog): role="dialog", заголовок и описание обязательны — без них Radix пишет в консоль. */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-[rgba(10,16,13,.45)]" />
        <D.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 max-h-[calc(100vh-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-line bg-surface text-ink shadow-pop',
            wide ? 'w-[min(760px,calc(100vw-32px))]' : 'w-[min(540px,calc(100vw-32px))]',
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <D.Title className="text-base font-semibold">{title}</D.Title>
              <D.Description className={description ? 'mt-0.5 text-[13px] text-muted' : 'sr'}>{description ?? title}</D.Description>
            </div>
            <D.Close className="rounded-md p-1 text-muted hover:bg-hover hover:text-ink" aria-label={t('Закрыть')}>
              <X size={18} />
            </D.Close>
          </div>
          <div className="px-5 py-4">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

/**
 * Всплывающая подсказка (Radix Tooltip). Только там, где без неё непонятно: кнопка-иконка, термин предметной
 * области, обрезанный текст, код вместо названия. Подсказка не повторяет видимый текст.
 */
export function Tip({ content, children, side = 'top' }: { content: ReactNode; children: React.ReactElement; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  if (!content) return children;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          collisionPadding={12}
          className="z-[70] max-w-[320px] rounded-md bg-ink px-2.5 py-1.5 text-xs leading-snug text-bg shadow-pop"
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
