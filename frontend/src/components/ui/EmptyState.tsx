import type { ReactNode } from 'react'
import { cx } from './cx'

interface EmptyStateProps {
  title: string
  description?: string
  /** Usually a link/button that gets the user out of the empty state. */
  action?: ReactNode
  /** No frame: use inside a Card. */
  inline?: boolean
}

export function EmptyState({ title, description, action, inline = false }: EmptyStateProps) {
  return (
    <div className={cx('space-y-2', !inline && 'rounded-md border border-line-soft px-6 py-8')}>
      <p className="font-medium text-ink-2">{title}</p>
      {description && <p className="max-w-reading text-small text-ink-3">{description}</p>}
      {action && <div className="pt-2">{action}</div>}
    </div>
  )
}
