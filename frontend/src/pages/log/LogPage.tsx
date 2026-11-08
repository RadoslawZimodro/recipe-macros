import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addDays, deleteEntry, foodLogKeys, getDay, todayInPoland } from '../../api/foodLog'
import { describeError } from '../../api/messages'
import { ErrorMessage } from '../../components/Field'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Skeleton, Spinner } from '../../components/ui/Spinner'
import { AddEntryForm } from './AddEntryForm'
import { DaySummary } from './DaySummary'
import { EntryList } from './EntryList'
import { GoalsForm } from './GoalsForm'
import { TrendChart } from './TrendChart'

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
    <div className="space-y-8">
      <h1 className="text-h1">Dziennik</h1>
      <div className="flex flex-wrap items-end gap-2">
        <Button variant="secondary" onClick={() => setDay(addDays(day, -1))}>
          Poprzedni dzień
        </Button>
        <div className="space-y-1">
          <label htmlFor="log-date" className="block text-small font-medium text-ink-2">
            Data
          </label>
          <Input
            id="log-date"
            type="date"
            value={day}
            max={today}
            onChange={(e) => e.target.value && e.target.value <= today && setDay(e.target.value)}
            className="w-44"
          />
        </div>
        <Button variant="secondary" onClick={() => setDay(addDays(day, 1))} disabled={day >= today}>
          Następny dzień
        </Button>
        {day !== today && (
          <Button variant="ghost" onClick={() => setDay(today)}>
            Dziś
          </Button>
        )}
      </div>

      {dayQuery.isPending && (
        <div className="space-y-4">
          <p className="flex items-center gap-2 text-ink-2">
            <Spinner />
            Ładowanie dnia…
          </p>
          <Skeleton className="h-40" />
        </div>
      )}
      {dayQuery.isError && <ErrorMessage message={describeError(dayQuery.error)} />}
      {dayQuery.isSuccess && (
        <>
          <DaySummary totals={dayQuery.data.totals} />
          <section aria-label="Wpisy" className="space-y-4">
            <h2 className="text-h3">Wpisy</h2>
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
