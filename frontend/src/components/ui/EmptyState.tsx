import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description?: string
  /** Usually a link/button that gets the user out of the empty state. */
  action?: ReactNode
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="space-y-2 rounded-md border border-line-soft px-6 py-12">
      <p className="font-display text-h4 font-semibold text-ink">{title}</p>
      {description && <p className="max-w-reading text-ink-2">{description}</p>}
      {action && <div className="pt-2">{action}</div>}
    </div>
  )
}
