import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { searchIngredients, type Ingredient } from '../api/ingredients'
import { describeError } from '../api/messages'
import { useDebounced } from '../hooks/useDebounced'
import { ErrorMessage, Field } from './Field'

interface Props {
  label: string
  onPick: (ingredient: Ingredient) => void
  // Ids already added, so they are not offered again.
  excludeIds?: number[]
  disabled?: boolean
  // Shown in the input instead of the typed text; typing again calls onClear.
  selected?: Ingredient | null
  onClear?: () => void
  // Adds kcal/100 g to each result (useful when the choice is about the numbers).
  showKcal?: boolean
}

/** Product search: type a name, pick a result. Searches the API after a short pause in typing. */
export function IngredientSearch({ label, onPick, excludeIds = [], disabled, selected, onClear, showKcal }: Props) {
  const inputId = useId()
  const [text, setText] = useState('')
  const term = useDebounced(text.trim(), 250)

  const search = useQuery({
    queryKey: ['ingredients', 'search', term],
    queryFn: () => searchIngredients(term),
    enabled: term.length > 0,
    placeholderData: keepPreviousData,
  })

  const results = (search.data?.items ?? []).filter((item) => !excludeIds.includes(item.id))

  return (
    <div className="space-y-2">
      <Field
        id={inputId}
        label={label}
        type="search"
        value={selected ? selected.canonical_name : text}
        onChange={(event) => {
          onClear?.()
          setText(event.target.value)
        }}
        placeholder="Wpisz nazwę produktu"
        autoComplete="off"
      />
      {text.trim().length > 0 && (
        <div aria-live="polite">
          {/* Before the first response for the typed text, show progress instead of a stale "empty". */}
          {(term === '' || search.isPending) && <p className="text-sm text-slate-500">Szukam…</p>}
          {search.isError && <ErrorMessage message={describeError(search.error)} />}
          {search.isSuccess && results.length === 0 && (
            <p className="text-sm text-slate-500">Brak pasujących produktów.</p>
          )}
          {results.length > 0 && (
            <ul
              aria-label="Wyniki wyszukiwania"
              className="divide-y divide-slate-200 rounded-md border border-slate-200 dark:divide-slate-700 dark:border-slate-700"
            >
              {results.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      onPick(item)
                      setText('')
                    }}
                    className="flex w-full justify-between px-3 py-2 text-left hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-slate-800"
                  >
                    <span>{item.canonical_name}</span>
                    {showKcal && (
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {item.kcal_per_100g} kcal/100 g
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
