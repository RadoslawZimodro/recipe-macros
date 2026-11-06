import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listMatches } from '../../api/pantry'
import { describeError } from '../../api/messages'

export function MatchesSection() {
  const matches = useQuery({ queryKey: ['pantry', 'recipes'], queryFn: listMatches })
  // The API sorts by match; sort again so the order never depends on it.
  const sorted = [...(matches.data ?? [])].sort((a, b) => b.percent - a.percent)

  return (
    <section aria-labelledby="matches-heading" className="space-y-3">
      <h2 id="matches-heading" className="text-xl font-semibold">
        Co możesz ugotować
      </h2>
      {matches.isPending && <p className="text-sm text-slate-500">Ładowanie…</p>}
      {matches.isError && (
        <div role="alert" className="text-sm text-red-600 dark:text-red-400">
          {describeError(matches.error)}{' '}
          <button type="button" className="underline" onClick={() => void matches.refetch()}>
            Spróbuj ponownie
          </button>
        </div>
      )}
      {matches.isSuccess && sorted.length === 0 && (
        <p className="text-sm text-slate-500">
          Brak pasujących przepisów. Dodaj produkty albo zaimportuj więcej przepisów.
        </p>
      )}
      <ul className="space-y-3">
        {sorted.map((match) => (
          <li
            key={match.recipe_id}
            className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
          >
            <div className="flex items-baseline justify-between gap-3">
              <Link to={`/recipes/${match.recipe_id}`} className="font-medium underline">
                {match.title}
              </Link>
              <span className="text-sm font-semibold">{Math.round(match.percent)}%</span>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              Masz {match.lines_have} z {match.lines_total} składników
            </p>
            {match.missing.length > 0 && (
              <div className="mt-2 text-sm">
                <p className="font-medium">Brakuje:</p>
                <ul className="list-disc pl-5">
                  {match.missing.map((line) => (
                    <li key={line.line_id}>
                      {line.raw_text}
                      {line.unlinked && (
                        <span className="text-slate-500"> (nierozpoznany produkt)</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
