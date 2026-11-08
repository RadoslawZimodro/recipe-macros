import { Button } from './Button'
import { cx } from './cx'

interface ErrorMessageProps {
  message: string | null
  /** When given, shows a "Spróbuj ponownie" button. */
  onRetry?: () => void
  /** No frame of its own: use inside a Card, where a boxed message would be a card in a card. */
  inline?: boolean
}

export function ErrorMessage({ message, onRetry, inline = false }: ErrorMessageProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className={cx(
        'flex flex-wrap items-center justify-between gap-3 text-small text-danger',
        !inline && 'rounded-sm border border-line bg-surface px-4 py-3',
      )}
    >
      {/* The icon means the error does not rely on colour alone (WCAG 1.4.1). */}
      <p className="flex items-start gap-2">
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="mt-0.5 size-4 shrink-0"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7.5v5.5M12 16.25v.01" />
        </svg>
        <span>{message}</span>
      </p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Spróbuj ponownie
        </Button>
      )}
    </div>
  )
}
