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
import { ErrorMessage } from '../../components/Field'
import { IngredientSearch } from '../../components/IngredientSearch'
import { Chip } from '../../components/ui/Chip'
import { EmptyState } from '../../components/ui/EmptyState'
import { Spinner } from '../../components/ui/Spinner'

function Status({
  query,
  empty,
  isEmpty,
}: {
  query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }
  empty: string
  isEmpty: boolean
}) {
  if (query.isPending) {
    return (
      <p className="flex items-center gap-2 text-small text-ink-2">
        <Spinner />
        Ładowanie…
      </p>
    )
  }
  if (query.isError) {
    return <ErrorMessage message={describeError(query.error)} onRetry={() => void query.refetch()} />
  }
  return isEmpty ? <EmptyState title={empty} /> : null
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
        <li key={item.ingredient_id}>
          <Chip onRemove={() => onRemove(item)} removeLabel={`Usuń ${item.name}`} removeDisabled={disabled}>
            {item.name}
          </Chip>
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
    <section aria-labelledby="pantry-heading" className="space-y-4">
      <h2 id="pantry-heading" className="text-h3">
        Moje produkty
      </h2>
      <IngredientSearch
        label="Dodaj produkt"
        excludeIds={items.map((item) => item.ingredient_id)}
        disabled={add.isPending}
        onPick={(ingredient) => {
          remove.reset()
          add.mutate(ingredient.id)
        }}
      />
      {(add.isError || remove.isError) && (
        <ErrorMessage message={describeError(remove.error ?? add.error)} />
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
    <section aria-labelledby="staples-heading" className="space-y-4">
      <h2 id="staples-heading" className="text-h3">
        Zawsze w domu
      </h2>
      <p className="text-small text-ink-2">
        Te produkty (np. sól, woda) liczą się jako dostępne w każdym przepisie.
      </p>
      <IngredientSearch
        label="Dodaj do „zawsze w domu”"
        excludeIds={own.map((item) => item.ingredient_id)}
        disabled={add.isPending}
        onPick={(ingredient) => {
          remove.reset()
          add.mutate(ingredient.id)
        }}
      />
      {(add.isError || remove.isError) && (
        <ErrorMessage message={describeError(remove.error ?? add.error)} />
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
        <p className="text-small text-ink-3">Domyślnie: {defaults.join(', ')}.</p>
      )}
    </section>
  )
}
