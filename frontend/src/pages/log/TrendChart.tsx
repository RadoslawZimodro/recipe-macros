import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { addDays, foodLogKeys, getDays } from '../../api/foodLog'
import { describeError } from '../../api/messages'
import { useAuth } from '../../auth/AuthProvider'
import { ErrorMessage } from '../../components/Field'

type Range = 7 | 30

// `today` ends the range. The API returns empty days too, so the chart has no gaps.
export function TrendChart({ today }: { today: string }) {
  const { user } = useAuth()
  const [range, setRange] = useState<Range>(7)
  const from = addDays(today, -(range - 1))
  const days = useQuery({
    queryKey: foodLogKeys.days(from, today),
    queryFn: () => getDays(from, today),
  })
  const goal = user?.daily_kcal_goal ?? null

  const option = (value: Range) => (
    <button
      type="button"
      aria-pressed={range === value}
      onClick={() => setRange(value)}
      className={`rounded-md px-3 py-1.5 text-sm ${range === value ? 'bg-emerald-600 text-white' : 'border border-slate-300 dark:border-slate-600'}`}
    >
      {value} dni
    </button>
  )

  const data =
    days.data?.days.map((d) => ({ day: d.day.slice(5), kcal: Math.round(d.total.kcal) })) ?? []
  const hasAny = days.data?.days.some((d) => d.entries > 0) ?? false

  return (
    <section
      aria-label="Wykres kalorii"
      className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Kalorie w czasie</h2>
        <div className="flex gap-2">
          {option(7)}
          {option(30)}
        </div>
      </div>
      {days.isPending && <p>Ładowanie wykresu…</p>}
      {days.isError && <ErrorMessage message={describeError(days.error)} />}
      {days.isSuccess && !hasAny && (
        <p className="text-slate-600 dark:text-slate-300">Brak wpisów w tym okresie.</p>
      )}
      {days.isSuccess && hasAny && (
        <div className="h-64 text-slate-600 dark:text-slate-300">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.25} />
              <XAxis
                dataKey="day"
                stroke="currentColor"
                tick={{ fill: 'currentColor', fontSize: 12 }}
              />
              <YAxis
                stroke="currentColor"
                tick={{ fill: 'currentColor', fontSize: 12 }}
                unit=" kcal"
                width={70}
              />
              <Tooltip
                contentStyle={{
                  background: '#ffffff',
                  color: '#0f172a',
                  border: '1px solid #cbd5e1',
                }}
                formatter={(value) => [`${value} kcal`, 'Szacunek']}
              />
              <Bar dataKey="kcal" name="kcal" fill="#10b981" />
              {goal !== null && (
                <ReferenceLine
                  y={goal}
                  stroke="#ef4444"
                  strokeDasharray="4 4"
                  label={{ value: 'Cel', fill: 'currentColor', position: 'insideTopRight' }}
                />
              )}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-xs text-slate-500 dark:text-slate-400">Wartości są szacunkowe.</p>
    </section>
  )
}
