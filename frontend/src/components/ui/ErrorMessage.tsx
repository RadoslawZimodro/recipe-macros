import { Button } from './Button'

interface ErrorMessageProps {
  message: string | null
  /** When given, shows a "Spróbuj ponownie" button. */
  onRetry?: () => void
}

export function ErrorMessage({ message, onRetry }: ErrorMessageProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-sm border border-line bg-surface px-4 py-3 text-small text-danger"
    >
      <p>{message}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Spróbuj ponownie
        </Button>
      )}
    </div>
  )
}
