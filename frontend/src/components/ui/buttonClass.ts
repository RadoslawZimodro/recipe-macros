import { cx } from './cx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const BASE =
  'press inline-flex h-10 items-center justify-center gap-2 rounded-sm px-4 text-body font-medium ' +
  'transition-[color,background-color,border-color,transform] duration-150 ease-soft ' +
  'disabled:cursor-not-allowed disabled:text-ink-4'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-on-accent hover:bg-accent-strong disabled:bg-raised',
  secondary: 'border border-control-border text-ink hover:bg-raised disabled:border-line',
  ghost: 'text-ink-2 hover:bg-raised hover:text-ink',
  danger: 'border border-control-border text-danger hover:bg-raised disabled:border-line',
}

/** Class string for anything that must look like a button, e.g. a router <Link>. */
export function buttonClass(variant: ButtonVariant = 'primary', className?: string): string {
  return cx(BASE, VARIANTS[variant], className)
}
