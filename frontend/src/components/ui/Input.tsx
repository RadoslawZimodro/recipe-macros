import type { InputHTMLAttributes, SelectHTMLAttributes } from 'react'
import { cx } from './cx'

const CONTROL =
  'block h-10 w-full rounded-sm border border-control-border bg-inset px-3 text-body text-ink ' +
  'placeholder:text-ink-3 transition-[border-color] duration-150 ease-soft ' +
  'hover:border-ink-3 disabled:cursor-not-allowed disabled:border-line disabled:text-ink-4'

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(CONTROL, className)} {...rest} />
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx(CONTROL, className)} {...rest} />
}
