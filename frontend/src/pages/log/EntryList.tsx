import { Link } from 'react-router-dom'
import type { FoodLogEntry } from '../../api/foodLog'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { fmt, macrosText } from './format'

export function EntryList({
  entries,
  onDelete,
  deletingId,
}: {
  entries: FoodLogEntry[]
  onDelete: (id: number) => void
  deletingId: number | null
}) {
  if (entries.length === 0) {
    return <EmptyState title="Nic jeszcze nie zapisano tego dnia." />
  }
  return (
    <ul className="divide-y divide-line-soft rounded-md border border-line bg-surface">
      {entries.map((entry) => (
        <li key={entry.id} className="flex items-start justify-between gap-4 p-4">
          <div className="space-y-1">
            <p className="font-medium">
              {entry.kind === 'recipe' && entry.recipe_id !== null ? (
                <Link
                  to={`/recipes/${entry.recipe_id}`}
                  className="text-accent underline underline-offset-2 hover:text-accent-strong"
                >
                  {entry.name}
                </Link>
              ) : (
                entry.name
              )}
              <span className="ml-2 text-small font-normal text-ink-3 tabular-nums">
                {entry.kind === 'recipe'
                  ? `${fmt(entry.servings ?? 0)} porcji`
                  : `${fmt(entry.grams ?? 0)} g`}
              </span>
            </p>
            <p className="text-small text-ink-2 tabular-nums">
              {entry.nutrition ? `${macrosText(entry.nutrition)} (szacunek)` : 'Brak danych o makro'}
            </p>
            {entry.is_estimate && <p className="text-caption text-ink-3">Część wartości to szacunek AI.</p>}
            {!entry.complete && (
              <p className="text-caption text-warning">
                Niepełne: policzono {entry.lines_counted ?? 0} z {entry.lines_total ?? 0} składników.
              </p>
            )}
          </div>
          <Button
            variant="secondary"
            onClick={() => onDelete(entry.id)}
            disabled={deletingId === entry.id}
            aria-label={`Usuń wpis: ${entry.name}`}
          >
            Usuń
          </Button>
        </li>
      ))}
    </ul>
  )
}
