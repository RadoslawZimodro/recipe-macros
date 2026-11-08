import type { ButtonHTMLAttributes } from 'react'
import { buttonClass } from './buttonClass'
import type { ButtonVariant } from './buttonClass'
import { Spinner } from './Spinner'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  /** Disables the button and shows a spinner; the label stays so the width does not jump. */
  loading?: boolean
}

export function Button({
  variant = 'primary',
  loading = false,
  type = 'button',
  className,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, className)}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}
