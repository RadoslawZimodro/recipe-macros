import type { DayTotals, GoalProgress } from '../../api/foodLog'
import { Card } from '../../components/ui/Card'
import { cx } from '../../components/ui/cx'
import { fmt } from './format'

/** Macro figure in the signature style: Fraunces numerals, tabular. */
const FIGURE = 'font-display text-h2 font-semibold tabular-nums text-ink'

function Progress({
  label,
  unit,
  progress,
  eaten,
}: {
  label: string
  unit: string
  progress: GoalProgress | null
  eaten: number
}) {
  if (!progress) {
    return (
      <div className="space-y-1">
        <p className="text-small font-medium text-ink-2">{label}</p>
        <p className={FIGURE}>
          {fmt(eaten)} {unit}
        </p>
        <p className="text-caption text-ink-3">Cel nie jest ustawiony</p>
      </div>
    )
  }
  const over = progress.remaining < 0
  return (
    <div className="space-y-1">
      <p className="text-small font-medium text-ink-2">{label}</p>
      <p className={FIGURE}>
        {fmt(progress.eaten)} / {fmt(progress.goal)} {unit}
      </p>
      <div
        role="progressbar"
        aria-label={`${label}: postęp celu`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(100, Math.round(progress.percent))}
        className="mt-2 h-2 overflow-hidden rounded-sm border border-line bg-inset"
      >
        <div
          className={cx('h-full', over ? 'bg-danger' : 'bg-accent')}
          style={{ width: `${Math.min(100, progress.percent)}%` }}
        />
      </div>
      <p className="pt-1 text-small text-ink-2 tabular-nums">
        {over
          ? `Przekroczono o ${fmt(-progress.remaining)} ${unit}`
          : `Zostało ${fmt(progress.remaining)} ${unit}`}{' '}
        ({fmt(progress.percent)}%)
      </p>
    </div>
  )
}

export function DaySummary({ totals }: { totals: DayTotals }) {
  return (
    <Card as="section" aria-label="Suma dnia" className="space-y-6">
      <h2 className="text-h3">Suma dnia</h2>
      <div className="grid gap-6 sm:grid-cols-2">
        <Progress label="Kalorie" unit="kcal" progress={totals.kcal} eaten={totals.total.kcal} />
        <Progress label="Białko" unit="g" progress={totals.protein} eaten={totals.total.protein} />
      </div>
      <p className="text-small font-medium text-ink-2 tabular-nums">
        Tłuszcze: {fmt(totals.total.fat)} g · Węglowodany: {fmt(totals.total.carbs)} g
      </p>
      <p className="border-t border-line-soft pt-4 text-caption text-ink-3">
        Wartości są szacunkowe
        {totals.is_estimate ? ' (część pochodzi z oszacowania AI)' : ''}.
        {!totals.complete && ' Suma jest niepełna: nie wszystkie składniki udało się policzyć.'}
      </p>
    </Card>
  )
}
