import { cx } from './cx'

/** Decorative: pair it with visible text (or a role="status" message) that says what is loading. */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      className={cx('size-4 motion-safe:animate-spin', className)}
    >
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  )
}

/** Placeholder block that keeps the layout from jumping while data loads. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx('rounded-sm bg-raised motion-safe:animate-pulse', className)} />
}
