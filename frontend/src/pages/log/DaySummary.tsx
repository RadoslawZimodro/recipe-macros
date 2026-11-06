import type { DayTotals, GoalProgress } from '../../api/foodLog'
import { fmt } from './format'

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
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-lg">
          {fmt(eaten)} {unit}
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400">Cel nie jest ustawiony</p>
      </div>
    )
  }
  const over = progress.remaining < 0
  return (
    <div>
      <p className="text-sm font-medium">{label}</p>
      <p className="text-lg">
        {fmt(progress.eaten)} / {fmt(progress.goal)} {unit}
      </p>
      <div
        role="progressbar"
        aria-label={`${label}: postęp celu`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(100, Math.round(progress.percent))}
        className="mt-1 h-2 overflow-hidden rounded bg-slate-200 dark:bg-slate-700"
      >
        <div
          className={`h-full ${over ? 'bg-red-500' : 'bg-emerald-600'}`}
          style={{ width: `${Math.min(100, progress.percent)}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
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
    <section
      aria-label="Suma dnia"
      className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
    >
      <h2 className="text-lg font-semibold">Suma dnia</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Progress label="Kalorie" unit="kcal" progress={totals.kcal} eaten={totals.total.kcal} />
        <Progress label="Białko" unit="g" progress={totals.protein} eaten={totals.total.protein} />
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Tłuszcze: {fmt(totals.total.fat)} g · Węglowodany: {fmt(totals.total.carbs)} g
      </p>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Wartości są szacunkowe
        {totals.is_estimate ? ' (część pochodzi z oszacowania AI)' : ''}.
        {!totals.complete && ' Suma jest niepełna: nie wszystkie składniki udało się policzyć.'}
      </p>
    </section>
  )
}
