import { Link } from 'react-router-dom'
import type { FoodLogEntry } from '../../api/foodLog'
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
    return <p className="text-slate-600 dark:text-slate-300">Nic jeszcze nie zapisano tego dnia.</p>
  }
  return (
    <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white dark:divide-slate-700 dark:border-slate-700 dark:bg-slate-800">
      {entries.map((entry) => (
        <li key={entry.id} className="flex items-start justify-between gap-3 p-3">
          <div className="space-y-0.5">
            <p className="font-medium">
              {entry.kind === 'recipe' && entry.recipe_id !== null ? (
                <Link
                  to={`/recipes/${entry.recipe_id}`}
                  className="text-emerald-700 underline dark:text-emerald-400"
                >
                  {entry.name}
                </Link>
              ) : (
                entry.name
              )}
              <span className="ml-2 text-sm font-normal text-slate-500 dark:text-slate-400">
                {entry.kind === 'recipe'
                  ? `${fmt(entry.servings ?? 0)} porcji`
                  : `${fmt(entry.grams ?? 0)} g`}
              </span>
            </p>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {entry.nutrition ? `${macrosText(entry.nutrition)} (szacunek)` : 'Brak danych o makro'}
            </p>
            {entry.is_estimate && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Część wartości to szacunek AI.
              </p>
            )}
            {!entry.complete && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                Niepełne: policzono {entry.lines_counted ?? 0} z {entry.lines_total ?? 0} składników.
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => onDelete(entry.id)}
            disabled={deletingId === entry.id}
            aria-label={`Usuń wpis: ${entry.name}`}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            Usuń
          </button>
        </li>
      ))}
    </ul>
  )
}
