import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addStaple,
  addToPantry,
  listPantry,
  listStaples,
  removeFromPantry,
  removeStaple,
  type PantryItem,
} from '../../api/pantry'
import { describeError } from '../../api/messages'
import { IngredientPicker } from './IngredientPicker'

function Status({
  query,
  empty,
  isEmpty,
}: {
  query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }
  empty: string
  isEmpty: boolean
}) {
  if (query.isPending) return <p className="text-sm text-slate-500">Ładowanie…</p>
  if (query.isError) {
    return (
      <div role="alert" className="text-sm text-red-600 dark:text-red-400">
        {describeError(query.error)}{' '}
        <button type="button" className="underline" onClick={() => void query.refetch()}>
          Spróbuj ponownie
        </button>
      </div>
    )
  }
  return isEmpty ? <p className="text-sm text-slate-500">{empty}</p> : null
}

function ItemList({
  items,
  onRemove,
  disabled,
}: {
  items: PantryItem[]
  onRemove: (item: PantryItem) => void
  disabled: boolean
}) {
  return (
    <ul className="flex flex-wrap gap-2">
      {items.map((item) => (
        <li
          key={item.ingredient_id}
          className="flex items-center gap-2 rounded-full border border-slate-300 bg-white py-1 pl-3 pr-1 text-sm dark:border-slate-600 dark:bg-slate-800"
        >
          {item.name}
          <button
            type="button"
            disabled={disabled}
            aria-label={`Usuń ${item.name}`}
            onClick={() => onRemove(item)}
            className="rounded-full px-2 hover:bg-slate-200 disabled:opacity-50 dark:hover:bg-slate-700"
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  )
}

export function PantrySection() {
  const queryClient = useQueryClient()
  const pantry = useQuery({ queryKey: ['pantry', 'items'], queryFn: listPantry })
  // The ['pantry'] prefix also covers the recipe matches, which depend on the pantry.
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['pantry'] })
  const add = useMutation({ mutationFn: addToPantry, onSuccess: refresh })
  const remove = useMutation({ mutationFn: removeFromPantry, onSuccess: refresh })
  const items = pantry.data ?? []

  return (
    <section aria-labelledby="pantry-heading" className="space-y-3">
      <h2 id="pantry-heading" className="text-xl font-semibold">
        Moje produkty
      </h2>
      <IngredientPicker
        label="Dodaj produkt"
        excludeIds={items.map((item) => item.ingredient_id)}
        disabled={add.isPending}
        onPick={(ingredient) => {
          remove.reset()
          add.mutate(ingredient.id)
        }}
      />
      {(add.isError || remove.isError) && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {describeError(remove.error ?? add.error)}
        </p>
      )}
      <Status
        query={pantry}
        isEmpty={items.length === 0}
        empty="Lodówka jest pusta. Dodaj pierwszy produkt."
      />
      <ItemList
        items={items}
        disabled={remove.isPending}
        onRemove={(item) => {
          add.reset()
          remove.mutate(item.ingredient_id)
        }}
      />
    </section>
  )
}

export function StaplesSection() {
  const queryClient = useQueryClient()
  const staples = useQuery({ queryKey: ['staples'], queryFn: listStaples })
  // Staples count as available in the matches, so only the recipe matches (not the pantry items) are refreshed too.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['staples'] }),
      queryClient.invalidateQueries({ queryKey: ['pantry', 'recipes'] }),
    ])
  const add = useMutation({ mutationFn: addStaple, onSuccess: refresh })
  const remove = useMutation({ mutationFn: removeStaple, onSuccess: refresh })
  const own = staples.data?.own ?? []
  const defaults = staples.data?.defaults ?? []

  return (
    <section aria-labelledby="staples-heading" className="space-y-3">
      <h2 id="staples-heading" className="text-xl font-semibold">
        Zawsze w domu
      </h2>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Te produkty (np. sól, woda) liczą się jako dostępne w każdym przepisie.
      </p>
      <IngredientPicker
        label="Dodaj do „zawsze w domu”"
        excludeIds={own.map((item) => item.ingredient_id)}
        disabled={add.isPending}
        onPick={(ingredient) => {
          remove.reset()
          add.mutate(ingredient.id)
        }}
      />
      {(add.isError || remove.isError) && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {describeError(remove.error ?? add.error)}
        </p>
      )}
      <Status query={staples} isEmpty={own.length === 0} empty="Nie dodano własnych produktów." />
      <ItemList
        items={own}
        disabled={remove.isPending}
        onRemove={(item) => {
          add.reset()
          remove.mutate(item.ingredient_id)
        }}
      />
      {defaults.length > 0 && (
        <p className="text-sm text-slate-500">Domyślnie: {defaults.join(', ')}.</p>
      )}
    </section>
  )
}
