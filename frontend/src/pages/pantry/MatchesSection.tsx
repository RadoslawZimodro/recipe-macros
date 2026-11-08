import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listMatches } from '../../api/pantry'
import { describeError } from '../../api/messages'
import { ErrorMessage } from '../../components/Field'
import { Card } from '../../components/ui/Card'
import { EmptyState } from '../../components/ui/EmptyState'
import { Spinner } from '../../components/ui/Spinner'

export function MatchesSection() {
  const matches = useQuery({ queryKey: ['pantry', 'recipes'], queryFn: listMatches })
  // The API sorts by match; sort again so the order never depends on it.
  const sorted = [...(matches.data ?? [])].sort((a, b) => b.percent - a.percent)

  return (
    <section aria-labelledby="matches-heading" className="space-y-4">
      <h2 id="matches-heading" className="text-h2">
        Co możesz ugotować
      </h2>
      {matches.isPending && (
        <p className="flex items-center gap-2 text-small text-ink-2">
          <Spinner />
          Ładowanie…
        </p>
      )}
      {matches.isError && (
        <ErrorMessage message={describeError(matches.error)} onRetry={() => void matches.refetch()} />
      )}
      {matches.isSuccess && sorted.length === 0 && (
        <EmptyState title="Brak pasujących przepisów. Dodaj produkty albo zaimportuj więcej przepisów." />
      )}
      <ul className="space-y-4">
        {sorted.map((match) => (
          <Card as="li" key={match.recipe_id} className="space-y-2">
            <div className="flex items-baseline justify-between gap-4">
              <Link
                to={`/recipes/${match.recipe_id}`}
                className="font-display text-h4 font-semibold text-ink underline underline-offset-2 hover:text-accent"
              >
                {match.title}
              </Link>
              <span className="font-display text-h3 font-semibold tabular-nums text-accent">
                {Math.round(match.percent)}%
              </span>
            </div>
            <p className="text-small text-ink-3">
              Masz {match.lines_have} z {match.lines_total} składników
            </p>
            {match.missing.length > 0 && (
              <div className="pt-2 text-small text-ink-2">
                <p className="font-medium text-ink">Brakuje:</p>
                <ul className="list-disc space-y-1 pt-1 pl-6">
                  {match.missing.map((line) => (
                    <li key={line.line_id}>
                      {line.raw_text}
                      {line.unlinked && <span className="text-ink-3"> (nierozpoznany produkt)</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        ))}
      </ul>
    </section>
  )
}
