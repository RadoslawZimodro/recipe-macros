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
import { Card } from '../../components/ui/Card'
import { EmptyState } from '../../components/ui/EmptyState'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Skeleton, Spinner } from '../../components/ui/Spinner'

type Range = '7' | '30'

// Chart colours come from the design tokens (CSS variables), never from literals.
const token = (name: string) => `var(--color-${name})`

// `today` ends the range. The API returns empty days too, so the chart has no gaps.
export function TrendChart({ today }: { today: string }) {
  const { user } = useAuth()
  const [range, setRange] = useState<Range>('7')
  const from = addDays(today, -(Number(range) - 1))
  const days = useQuery({
    queryKey: foodLogKeys.days(from, today),
    queryFn: () => getDays(from, today),
  })
  const goal = user?.daily_kcal_goal ?? null

  const data =
    days.data?.days.map((d) => ({ day: d.day.slice(5), kcal: Math.round(d.total.kcal) })) ?? []
  const hasAny = days.data?.days.some((d) => d.entries > 0) ?? false

  return (
    <Card as="section" aria-label="Wykres kalorii" className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-h3">Kalorie w czasie</h2>
        <SegmentedControl
          label="Zakres wykresu"
          value={range}
          onChange={setRange}
          options={[
            { value: '7', label: '7 dni' },
            { value: '30', label: '30 dni' },
          ]}
        />
      </div>
      {days.isPending && (
        <div className="space-y-4">
          <p className="flex items-center gap-2 text-ink-2">
            <Spinner />
            Ładowanie wykresu…
          </p>
          <Skeleton className="h-64" />
        </div>
      )}
      {days.isError && <ErrorMessage inline message={describeError(days.error)} />}
      {days.isSuccess && !hasAny && <EmptyState inline title="Brak wpisów w tym okresie." />}
      {days.isSuccess && hasAny && (
        <>
          {/* The chart is visual only; screen readers get the same numbers as a list. */}
          <ul className="sr-only" aria-label="Kalorie dzień po dniu">
            {data.map((d) => (
              <li key={d.day}>
                {d.day}: {d.kcal} kcal
              </li>
            ))}
          </ul>
          <div aria-hidden="true" className="h-64 text-ink-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data}>
                <CartesianGrid vertical={false} stroke={token('line')} />
                <XAxis
                  dataKey="day"
                  stroke={token('line-strong')}
                  tick={{ fill: 'currentColor', fontSize: 12 }}
                />
                <YAxis
                  stroke={token('line-strong')}
                  tick={{ fill: 'currentColor', fontSize: 12 }}
                  unit=" kcal"
                  width={70}
                />
                <Tooltip
                  cursor={{ fill: token('line-soft') }}
                  contentStyle={{
                    background: token('raised'),
                    color: token('ink'),
                    border: `1px solid ${token('line-strong')}`,
                    borderRadius: 'var(--radius-sm)',
                  }}
                  formatter={(value) => [`${value} kcal`, 'Szacunek']}
                />
                <Bar dataKey="kcal" name="kcal" fill={token('accent')} />
                {goal !== null && (
                  <ReferenceLine
                    y={goal}
                    stroke={token('warning')}
                    strokeDasharray="4 4"
                    label={{ value: 'Cel', fill: token('warning'), position: 'insideTopRight' }}
                  />
                )}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
      <p className="text-caption text-ink-3">Wartości są szacunkowe.</p>
    </Card>
  )
}
