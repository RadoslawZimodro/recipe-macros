import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addDays, deleteEntry, foodLogKeys, getDay, todayInPoland } from '../../api/foodLog'
import { describeError } from '../../api/messages'
import { ErrorMessage } from '../../components/Field'
import { AddEntryForm } from './AddEntryForm'
import { DaySummary } from './DaySummary'
import { EntryList } from './EntryList'
import { GoalsForm } from './GoalsForm'
import { TrendChart } from './TrendChart'

const NAV_BUTTON =
  'rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700'

export function LogPage() {
  const queryClient = useQueryClient()
  const today = todayInPoland()
  const [day, setDay] = useState(today)
  const dayQuery = useQuery({ queryKey: foodLogKeys.day(day), queryFn: () => getDay(day) })
  const remove = useMutation({
    mutationFn: deleteEntry,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: foodLogKeys.all }),
  })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dziennik</h1>
      <div className="flex flex-wrap items-end gap-2">
        <button type="button" className={NAV_BUTTON} onClick={() => setDay(addDays(day, -1))}>
          Poprzedni dzień
        </button>
        <div className="space-y-1">
          <label htmlFor="log-date" className="block text-sm font-medium">
            Data
          </label>
          <input
            id="log-date"
            type="date"
            value={day}
            max={today}
            onChange={(e) => e.target.value && e.target.value <= today && setDay(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 dark:border-slate-600 dark:bg-slate-900"
          />
        </div>
        <button
          type="button"
          className={NAV_BUTTON}
          onClick={() => setDay(addDays(day, 1))}
          disabled={day >= today}
        >
          Następny dzień
        </button>
        {day !== today && (
          <button type="button" className={NAV_BUTTON} onClick={() => setDay(today)}>
            Dziś
          </button>
        )}
      </div>

      {dayQuery.isPending && <p>Ładowanie dnia…</p>}
      {dayQuery.isError && <ErrorMessage message={describeError(dayQuery.error)} />}
      {dayQuery.isSuccess && (
        <>
          <DaySummary totals={dayQuery.data.totals} />
          <section aria-label="Wpisy" className="space-y-2">
            <h2 className="text-lg font-semibold">Wpisy</h2>
            <ErrorMessage message={remove.isError ? describeError(remove.error) : null} />
            <EntryList
              entries={dayQuery.data.entries}
              onDelete={(id) => remove.mutate(id)}
              deletingId={remove.isPending ? remove.variables : null}
            />
          </section>
        </>
      )}

      <AddEntryForm day={day} />
      <TrendChart today={today} />
      <GoalsForm />
    </div>
  )
}
