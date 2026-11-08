import { useId } from 'react'
import type { KeyboardEvent } from 'react'
import { cx } from './cx'

export interface SegmentOption<T extends string> {
  value: T
  label: string
}

interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  /** Accessible name of the group. */
  label: string
  /** "tabs": switches a panel (role=tab, arrow keys). "toggle": picks a setting (aria-pressed). */
  mode?: 'tabs' | 'toggle'
  /** In tabs mode, the id of the tabpanel the control switches. */
  panelId?: string
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  mode = 'toggle',
  panelId,
}: SegmentedControlProps<T>) {
  const base = useId()
  const tabs = mode === 'tabs'

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (!tabs) return
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = options[(options.findIndex((o) => o.value === value) + step + options.length) % options.length]
    onChange(next.value)
    document.getElementById(`${base}-${next.value}`)?.focus()
  }

  return (
    <div
      role={tabs ? 'tablist' : 'group'}
      aria-label={label}
      onKeyDown={onKeyDown}
      className="inline-flex gap-1 rounded-sm border border-line bg-inset p-1"
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            id={`${base}-${o.value}`}
            type="button"
            role={tabs ? 'tab' : undefined}
            aria-selected={tabs ? active : undefined}
            aria-pressed={tabs ? undefined : active}
            aria-controls={tabs ? panelId : undefined}
            tabIndex={tabs && !active ? -1 : undefined}
            onClick={() => onChange(o.value)}
            className={cx(
              'press h-8 rounded-sm px-3 text-small font-medium transition-[color,background-color] duration-150 ease-soft',
              active ? 'bg-accent text-on-accent' : 'text-ink-2 hover:bg-raised hover:text-ink',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
