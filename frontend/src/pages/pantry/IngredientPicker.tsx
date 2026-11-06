import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'
import { searchIngredients, type Ingredient } from '../../api/pantry'
import { describeError } from '../../api/messages'

interface Props {
  label: string
  // Ids already added, so they are not offered again.
  excludeIds: number[]
  disabled?: boolean
  onPick: (ingredient: Ingredient) => void
}

/** Product search: type a name, pick a result. Searches the API after a short pause in typing. */
export function IngredientPicker({ label, excludeIds, disabled, onPick }: Props) {
  const inputId = useId()
  const [text, setText] = useState('')
  const [term, setTerm] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setTerm(text.trim()), 250)
    return () => clearTimeout(timer)
  }, [text])

  const search = useQuery({
    queryKey: ['ingredient-search', term],
    queryFn: () => searchIngredients(term),
    enabled: term.length > 0,
  })

  const results = (search.data?.items ?? []).filter((item) => !excludeIds.includes(item.id))

  return (
    <div>
      <label htmlFor={inputId} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      <input
        id={inputId}
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Wpisz nazwę produktu"
        autoComplete="off"
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900"
      />
      {term.length > 0 && (
        <div className="mt-2" aria-live="polite">
          {search.isPending && <p className="text-sm text-slate-500">Szukam…</p>}
          {search.isError && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {describeError(search.error)}
            </p>
          )}
          {search.isSuccess && results.length === 0 && (
            <p className="text-sm text-slate-500">Brak pasujących produktów.</p>
          )}
          {results.length > 0 && (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
              {results.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      onPick(item)
                      setText('')
                      setTerm('')
                    }}
                    className="w-full px-3 py-2 text-left hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-slate-800"
                  >
                    {item.canonical_name}
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
