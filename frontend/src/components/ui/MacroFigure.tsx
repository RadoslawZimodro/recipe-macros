import { cx } from './cx'

const nf = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 1 })

interface MacroFigureProps {
  label: string
  value: number
  unit: string
  /** Prefixes the number with "~": macro values are estimates (AGENTS.md section 6). */
  estimate?: boolean
  size?: 'lg' | 'md'
}

/** The signature element: a large tabular Fraunces numeral over a quiet caption label. */
export function MacroFigure({ label, value, unit, estimate = true, size = 'md' }: MacroFigureProps) {
  return (
    <div>
      <p className="text-caption font-medium text-ink-3">{label}</p>
      <p className="flex items-baseline gap-1">
        <span className={cx('font-display font-semibold tabular-nums text-ink', size === 'lg' ? 'text-display' : 'text-h2')}>
          {estimate ? '~' : ''}
          {nf.format(value)}
        </span>
        <span className="text-small text-ink-3">{unit}</span>
      </p>
    </div>
  )
}
