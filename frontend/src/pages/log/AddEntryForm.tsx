import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  addEntry,
  foodLogKeys,
  loggedAtFor,
  searchIngredients,
  type IngredientOut,
} from '../../api/foodLog'
import { listRecipes } from '../../api/recipes'
import { describeError } from '../../api/messages'
import { ErrorMessage, Field } from '../../components/Field'
import { useDebounced } from './useDebounced'

type Mode = 'recipe' | 'product'

const SELECT_CLASS =
  'block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-600/30 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100'

function SubmitButton({ disabled }: { disabled: boolean }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
    >
      Dodaj do dziennika
    </button>
  )
}

function RecipePicker({ day }: { day: string }) {
  const queryClient = useQueryClient()
  const recipes = useQuery({ queryKey: ['recipes', 'picker'], queryFn: () => listRecipes('', 0, 100) })
  const [recipeId, setRecipeId] = useState('')
  const [servings, setServings] = useState('1')
  const add = useMutation({
    mutationFn: () =>
      addEntry({
        recipe_id: Number(recipeId),
        servings: Number(servings),
        logged_at: loggedAtFor(day),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: foodLogKeys.all }),
  })

  if (recipes.isPending) return <p>Ładowanie przepisów…</p>
  if (recipes.isError) return <ErrorMessage message={describeError(recipes.error)} />
  if (recipes.data.items.length === 0) {
    return <p className="text-slate-600 dark:text-slate-300">Nie masz jeszcze żadnych przepisów.</p>
  }

  const valid = recipeId !== '' && Number(servings) > 0
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (valid) add.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="space-y-1">
        <label htmlFor="log-recipe" className="block text-sm font-medium">
          Przepis
        </label>
        <select
          id="log-recipe"
          value={recipeId}
          onChange={(e) => setRecipeId(e.target.value)}
          className={SELECT_CLASS}
        >
          <option value="">Wybierz przepis…</option>
          {recipes.data.items.map((recipe) => (
            <option key={recipe.id} value={recipe.id}>
              {recipe.title}
            </option>
          ))}
        </select>
      </div>
      <Field
        id="log-servings"
        label="Liczba porcji"
        type="number"
        min="0.25"
        max="100"
        step="0.25"
        value={servings}
        onChange={(e) => setServings(e.target.value)}
      />
      <ErrorMessage message={add.isError ? describeError(add.error) : null} />
      <SubmitButton disabled={!valid || add.isPending} />
    </form>
  )
}

function ProductPicker({ day }: { day: string }) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [chosen, setChosen] = useState<IngredientOut | null>(null)
  const [grams, setGrams] = useState('100')
  const q = useDebounced(search.trim(), 250)
  const results = useQuery({
    queryKey: ['ingredients', 'search', q],
    queryFn: () => searchIngredients(q),
    enabled: q.length > 0 && chosen === null,
  })
  const add = useMutation({
    mutationFn: (ingredient: IngredientOut) =>
      addEntry({
        ingredient_id: ingredient.id,
        grams: Number(grams),
        logged_at: loggedAtFor(day),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: foodLogKeys.all }),
  })

  const valid = chosen !== null && Number(grams) > 0
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (chosen && valid) add.mutate(chosen)
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field
        id="log-product-search"
        label="Produkt"
        type="search"
        placeholder="Szukaj produktu…"
        value={chosen ? chosen.canonical_name : search}
        onChange={(e) => {
          setChosen(null)
          setSearch(e.target.value)
        }}
      />
      {chosen === null && search.trim().length > 0 && (
        <div>
          {(results.isPending || q !== search.trim()) && <p>Szukam…</p>}
          {results.isError && <ErrorMessage message={describeError(results.error)} />}
          {results.isSuccess && q === search.trim() && results.data.items.length === 0 && (
            <p className="text-slate-600 dark:text-slate-300">Nie znaleziono produktów.</p>
          )}
          {results.isSuccess && q === search.trim() && results.data.items.length > 0 && (
            <ul
              aria-label="Wyniki wyszukiwania"
              className="divide-y divide-slate-200 rounded-md border border-slate-200 dark:divide-slate-700 dark:border-slate-700"
            >
              {results.data.items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => setChosen(item)}
                    className="flex w-full justify-between px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                  >
                    <span>{item.canonical_name}</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {item.kcal_per_100g} kcal/100 g
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <Field
        id="log-grams"
        label="Gramy"
        type="number"
        min="1"
        max="10000"
        step="1"
        value={grams}
        onChange={(e) => setGrams(e.target.value)}
      />
      <ErrorMessage message={add.isError ? describeError(add.error) : null} />
      <SubmitButton disabled={!valid || add.isPending} />
    </form>
  )
}

export function AddEntryForm({ day }: { day: string }) {
  const [mode, setMode] = useState<Mode>('recipe')
  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => setMode(value)}
      className={`rounded-md px-3 py-1.5 text-sm ${mode === value ? 'bg-emerald-600 text-white' : 'border border-slate-300 dark:border-slate-600'}`}
    >
      {label}
    </button>
  )
  return (
    <section
      aria-label="Dodaj wpis"
      className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
    >
      <h2 className="text-lg font-semibold">Dodaj wpis</h2>
      <div role="tablist" className="flex gap-2">
        {tab('recipe', 'Porcja przepisu')}
        {tab('product', 'Produkt w gramach')}
      </div>
      {mode === 'recipe' ? <RecipePicker day={day} /> : <ProductPicker day={day} />}
    </section>
  )
}
