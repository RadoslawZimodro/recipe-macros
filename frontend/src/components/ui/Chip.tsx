import type { ReactNode } from 'react'
import { cx } from './cx'

interface ChipProps {
  children: ReactNode
  /** "estimate" marks values that are estimates (AGENTS.md section 6). */
  tone?: 'neutral' | 'estimate'
  /** Makes the chip removable; the 40px remove button needs removeLabel for screen readers. */
  onRemove?: () => void
  removeLabel?: string
  removeDisabled?: boolean
}

export function Chip({ children, tone = 'neutral', onRemove, removeLabel, removeDisabled }: ChipProps) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-sm border border-line bg-surface',
        tone === 'estimate' ? 'text-warning' : 'text-ink-2',
        onRemove ? 'min-h-10 pl-3 text-small' : 'px-2 text-caption',
      )}
    >
      {children}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          disabled={removeDisabled}
          aria-label={removeLabel}
          className="press inline-flex size-10 items-center justify-center rounded-sm text-ink-3 transition-[color,background-color] duration-150 ease-soft hover:bg-raised hover:text-ink disabled:cursor-not-allowed disabled:text-ink-4"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="size-4">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      )}
    </span>
  )
}
